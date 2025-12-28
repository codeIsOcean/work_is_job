# ============================================================
# СЕРВИС ХЕШИРОВАНИЯ ИЗОБРАЖЕНИЙ (pHash + dHash)
# ============================================================
# Этот файл реализует perceptual hashing для обнаружения
# похожих изображений даже после изменения размера/сжатия.
#
# Используемые алгоритмы:
# - pHash (Perceptual Hash): устойчив к ресайзу и сжатию
# - dHash (Difference Hash): ловит изменения яркости
#
# Вместе pHash + dHash дают лучшее покрытие разных типов
# модификаций изображений.
# ============================================================

# Импорт стандартных библиотек
from io import BytesIO
# Импорт для аннотации типов
from typing import Optional, Tuple, NamedTuple
# Импорт для работы с логами
import logging

# Импорт библиотеки для работы с изображениями
from PIL import Image
# Импорт библиотеки для вычисления perceptual hash
import imagehash


# ============================================================
# НАСТРОЙКА ЛОГИРОВАНИЯ
# ============================================================
# Создаём логгер для этого модуля
logger = logging.getLogger(__name__)


# ============================================================
# ТИПЫ ДАННЫХ
# ============================================================
# NamedTuple для хранения пары хешей (pHash + dHash)
class ImageHashes(NamedTuple):
    """
    Контейнер для пары хешей изображения.

    Attributes:
        phash: Perceptual hash в hex формате (16 символов)
        dhash: Difference hash в hex формате (16 символов)
    """
    # pHash - основной хеш, устойчив к ресайзу
    phash: str
    # dHash - дополнительный хеш, ловит изменения яркости
    dhash: str


# ============================================================
# КОНСТАНТЫ
# ============================================================
# Размер хеша в битах (64 бита = 16 hex символов)
HASH_SIZE: int = 8
# Максимальный размер изображения для обработки (пиксели)
# Большие изображения ресайзятся для экономии памяти
MAX_IMAGE_SIZE: int = 1024


# ============================================================
# РЕГИОНЫ ДЛЯ ДЕТЕКЦИИ ЛОГО
# ============================================================
# Предопределённые области изображения где обычно находится лого
# Значения в процентах от размера изображения (0.0 - 1.0)
# Формат: (left%, top%, right%, bottom%)
LOGO_REGIONS = {
    # Верхний левый угол (20% ширины, 15% высоты)
    'top_left': (0.0, 0.0, 0.20, 0.15),
    # Верхний правый угол
    'top_right': (0.80, 0.0, 1.0, 0.15),
    # Нижний левый угол
    'bottom_left': (0.0, 0.85, 0.20, 1.0),
    # Нижний правый угол
    'bottom_right': (0.80, 0.85, 1.0, 1.0),
    # Центр сверху (для водяных знаков)
    'top_center': (0.35, 0.0, 0.65, 0.12),
    # Центр снизу
    'bottom_center': (0.35, 0.88, 0.65, 1.0),
}


# ============================================================
# КЛАСС СЕРВИСА ХЕШИРОВАНИЯ
# ============================================================
class HashService:
    """
    Сервис для вычисления и сравнения perceptual hash изображений.

    Использует два алгоритма хеширования:
    - pHash: DCT-based, устойчив к ресайзу, сжатию, небольшим правкам
    - dHash: Gradient-based, дополняет pHash для лучшего покрытия

    Пример использования:
        service = HashService()
        hashes = service.compute_hash(image_bytes)
        distance = service.compare(hashes.phash, stored_phash)
        if distance <= threshold:
            print("Изображение похоже!")
    """

    def __init__(self, hash_size: int = HASH_SIZE) -> None:
        """
        Инициализация сервиса хеширования.

        Args:
            hash_size: Размер хеша в битах (по умолчанию 8 = 64 бита)
        """
        # Сохраняем размер хеша для использования в методах
        self._hash_size = hash_size

    def compute_hash(self, image_data: bytes) -> Optional[ImageHashes]:
        """
        Вычисляет pHash и dHash для изображения.

        Args:
            image_data: Байты изображения (JPEG, PNG, etc.)

        Returns:
            ImageHashes с phash и dhash в hex формате,
            или None если изображение не удалось обработать
        """
        try:
            # Открываем изображение из байтов
            # BytesIO создаёт файлоподобный объект из байтов
            image = Image.open(BytesIO(image_data))

            # Конвертируем в RGB если нужно (для прозрачных PNG)
            # pHash работает с RGB, не с RGBA или P mode
            if image.mode not in ('RGB', 'L'):
                # Создаём белый фон для прозрачных изображений
                background = Image.new('RGB', image.size, (255, 255, 255))
                # Накладываем изображение на белый фон
                if image.mode == 'RGBA':
                    background.paste(image, mask=image.split()[3])
                else:
                    background.paste(image)
                image = background

            # Ресайзим большие изображения для экономии памяти
            # Это не влияет на качество хеша (pHash всё равно ресайзит)
            if max(image.size) > MAX_IMAGE_SIZE:
                # Вычисляем коэффициент масштабирования
                ratio = MAX_IMAGE_SIZE / max(image.size)
                # Новые размеры с сохранением пропорций
                new_size = (int(image.width * ratio), int(image.height * ratio))
                # Ресайзим с высоким качеством
                image = image.resize(new_size, Image.Resampling.LANCZOS)

            # Вычисляем pHash (perceptual hash)
            # pHash использует DCT для выделения низкочастотных компонент
            phash = imagehash.phash(image, hash_size=self._hash_size)

            # Вычисляем dHash (difference hash)
            # dHash анализирует градиенты яркости между соседними пикселями
            dhash = imagehash.dhash(image, hash_size=self._hash_size)

            # Возвращаем хеши в hex формате (строки по 16 символов)
            return ImageHashes(phash=str(phash), dhash=str(dhash))

        except Exception as e:
            # Логируем ошибку но не падаем - возвращаем None
            logger.warning(f"Ошибка вычисления хеша изображения: {e}")
            return None

    def compare(self, hash1: str, hash2: str) -> int:
        """
        Вычисляет расстояние Хэмминга между двумя хешами.

        Расстояние Хэмминга = количество различающихся битов.
        Чем меньше расстояние, тем более похожи изображения.

        Args:
            hash1: Первый хеш в hex формате
            hash2: Второй хеш в hex формате

        Returns:
            Расстояние Хэмминга (0 = идентичные, 64 = полностью разные)
        """
        try:
            # Преобразуем hex строки обратно в объекты imagehash
            h1 = imagehash.hex_to_hash(hash1)
            h2 = imagehash.hex_to_hash(hash2)
            # Оператор - для imagehash возвращает расстояние Хэмминга
            return h1 - h2
        except Exception as e:
            # При ошибке возвращаем максимальное расстояние
            logger.warning(f"Ошибка сравнения хешей: {e}")
            return 64  # Максимальное расстояние = полностью разные

    def is_similar(
        self,
        phash1: str,
        dhash1: Optional[str],
        phash2: str,
        dhash2: Optional[str],
        threshold: int = 10
    ) -> Tuple[bool, int]:
        """
        Проверяет похожи ли два изображения на основе их хешей.

        Использует оба хеша (pHash и dHash) для более точного сравнения.
        Изображения считаются похожими если ОБА хеша ниже порога,
        или если один хеш NULL и другой ниже порога.

        Args:
            phash1: pHash первого изображения
            dhash1: dHash первого изображения (может быть None)
            phash2: pHash второго изображения
            dhash2: dHash второго изображения (может быть None)
            threshold: Максимальное расстояние для срабатывания

        Returns:
            Tuple[is_similar: bool, min_distance: int]
            - is_similar: True если изображения похожи
            - min_distance: Минимальное расстояние между хешами
        """
        # Вычисляем расстояние по pHash (обязательный)
        phash_distance = self.compare(phash1, phash2)

        # Если pHash уже превышает порог - изображения точно разные
        if phash_distance > threshold:
            return (False, phash_distance)

        # Если dHash доступен для обоих изображений - проверяем и его
        if dhash1 is not None and dhash2 is not None:
            dhash_distance = self.compare(dhash1, dhash2)
            # Берём минимальное расстояние из двух хешей
            min_distance = min(phash_distance, dhash_distance)
            # Изображения похожи если минимальное расстояние в пределах порога
            return (min_distance <= threshold, min_distance)

        # Если dHash не доступен - используем только pHash
        return (phash_distance <= threshold, phash_distance)

    def compute_region_hash(
        self,
        image_data: bytes,
        region: str = 'top_left'
    ) -> Optional[ImageHashes]:
        """
        Вычисляет хеш для определённой области изображения (лого).

        Используется для детекции лого которое обычно в углу.
        Даже если основное изображение меняется, лого остаётся.

        Args:
            image_data: Байты изображения
            region: Название региона из LOGO_REGIONS
                    ('top_left', 'top_right', 'bottom_left', 'bottom_right',
                     'top_center', 'bottom_center')

        Returns:
            ImageHashes для области или None при ошибке
        """
        try:
            # Проверяем что регион существует
            if region not in LOGO_REGIONS:
                logger.warning(f"Неизвестный регион: {region}")
                return None

            # Открываем изображение
            image = Image.open(BytesIO(image_data))

            # Конвертируем в RGB если нужно
            if image.mode not in ('RGB', 'L'):
                background = Image.new('RGB', image.size, (255, 255, 255))
                if image.mode == 'RGBA':
                    background.paste(image, mask=image.split()[3])
                else:
                    background.paste(image)
                image = background

            # Получаем координаты региона в процентах
            left_pct, top_pct, right_pct, bottom_pct = LOGO_REGIONS[region]

            # Преобразуем проценты в пиксели
            width, height = image.size
            left = int(width * left_pct)
            top = int(height * top_pct)
            right = int(width * right_pct)
            bottom = int(height * bottom_pct)

            # Вырезаем область
            # crop() принимает (left, upper, right, lower)
            cropped = image.crop((left, top, right, bottom))

            # Проверяем что область достаточно большая
            if cropped.width < 32 or cropped.height < 32:
                logger.warning(f"Область слишком маленькая: {cropped.size}")
                return None

            # Вычисляем хеши для области
            phash = imagehash.phash(cropped, hash_size=self._hash_size)
            dhash = imagehash.dhash(cropped, hash_size=self._hash_size)

            return ImageHashes(phash=str(phash), dhash=str(dhash))

        except Exception as e:
            logger.warning(f"Ошибка вычисления хеша области {region}: {e}")
            return None

    def compute_all_region_hashes(
        self,
        image_data: bytes
    ) -> dict[str, ImageHashes]:
        """
        Вычисляет хеши для всех предопределённых регионов.

        Полезно для определения где находится лого на изображении.
        Админ может сравнить хеши разных областей.

        Args:
            image_data: Байты изображения

        Returns:
            Словарь {region_name: ImageHashes}
            Регионы с ошибками не включаются
        """
        result = {}
        # Проходим по всем регионам
        for region_name in LOGO_REGIONS:
            # Вычисляем хеш для региона
            hashes = self.compute_region_hash(image_data, region_name)
            # Добавляем только успешные
            if hashes is not None:
                result[region_name] = hashes
        return result


# ============================================================
# ГЛОБАЛЬНЫЙ ЭКЗЕМПЛЯР СЕРВИСА
# ============================================================
# Создаём глобальный экземпляр для использования в других модулях
# Это паттерн Singleton - один экземпляр на всё приложение
_hash_service = HashService()


# ============================================================
# ФУНКЦИИ-ОБЁРТКИ ДЛЯ УДОБНОГО ИМПОРТА
# ============================================================
def compute_image_hash(image_data: bytes) -> Optional[ImageHashes]:
    """
    Вычисляет pHash и dHash для изображения.

    Это функция-обёртка для удобного импорта:
        from bot.services.scam_media import compute_image_hash

    Args:
        image_data: Байты изображения

    Returns:
        ImageHashes или None при ошибке
    """
    return _hash_service.compute_hash(image_data)


def compare_hashes(hash1: str, hash2: str) -> int:
    """
    Вычисляет расстояние Хэмминга между двумя хешами.

    Это функция-обёртка для удобного импорта:
        from bot.services.scam_media import compare_hashes

    Args:
        hash1: Первый хеш в hex формате
        hash2: Второй хеш в hex формате

    Returns:
        Расстояние Хэмминга (0-64)
    """
    return _hash_service.compare(hash1, hash2)


def compute_logo_hash(image_data: bytes, region: str = 'top_left') -> Optional[ImageHashes]:
    """
    Вычисляет хеш для области лого на изображении.

    Используется для детекции повторяющихся лого/водяных знаков
    даже если основное содержимое изображения меняется.

    Args:
        image_data: Байты изображения
        region: Область где искать лого
                'top_left' - верхний левый угол
                'top_right' - верхний правый угол
                'bottom_left' - нижний левый угол
                'bottom_right' - нижний правый угол
                'top_center' - центр сверху
                'bottom_center' - центр снизу

    Returns:
        ImageHashes для области лого или None при ошибке
    """
    return _hash_service.compute_region_hash(image_data, region)


def get_available_logo_regions() -> list[str]:
    """
    Возвращает список доступных регионов для детекции лого.

    Returns:
        ['top_left', 'top_right', 'bottom_left', 'bottom_right',
         'top_center', 'bottom_center']
    """
    return list(LOGO_REGIONS.keys())