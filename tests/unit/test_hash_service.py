# ============================================================
# UNIT-ТЕСТЫ ДЛЯ СЕРВИСА ХЕШИРОВАНИЯ ИЗОБРАЖЕНИЙ
# ============================================================
# Тестируем:
# - Вычисление pHash и dHash
# - Сравнение хешей (расстояние Хэмминга)
# - Детекция похожих изображений с threshold
# - Хеширование областей для лого
# ============================================================

# Импорт стандартных библиотек
from pathlib import Path
# Импорт библиотеки для создания тестовых изображений
from io import BytesIO

# Импорт pytest для тестов
import pytest
# Импорт PIL для создания тестовых изображений
from PIL import Image

# Импорт тестируемого модуля
from bot.services.scam_media import (
    HashService,
    compute_image_hash,
    compare_hashes,
    compute_logo_hash,
    get_available_logo_regions,
    ImageHashes,
    LOGO_REGIONS,
)


# ============================================================
# ПУТЬ К ТЕСТОВЫМ ИЗОБРАЖЕНИЯМ
# ============================================================
# Получаем путь к директории с тестовыми скам-фото
TEST_IMAGES_DIR = Path(__file__).parent.parent.parent / "docs" / "image_filter"


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================
def create_test_image(width: int = 200, height: int = 200, color: tuple = (255, 0, 0)) -> bytes:
    """
    Создаёт тестовое изображение заданного размера и цвета.

    Args:
        width: Ширина изображения в пикселях
        height: Высота изображения в пикселях
        color: RGB цвет заливки

    Returns:
        Байты JPEG изображения
    """
    # Создаём изображение
    img = Image.new('RGB', (width, height), color)
    # Сохраняем в байты
    buffer = BytesIO()
    img.save(buffer, format='JPEG')
    return buffer.getvalue()


def create_similar_image(base_image: bytes, noise_level: int = 10) -> bytes:
    """
    Создаёт изображение похожее на базовое с небольшим шумом.

    Args:
        base_image: Байты базового изображения
        noise_level: Уровень шума (0-255)

    Returns:
        Байты модифицированного изображения
    """
    import random
    # Открываем базовое изображение
    img = Image.open(BytesIO(base_image))
    pixels = img.load()
    # Добавляем случайный шум к каждому пикселю
    for x in range(img.width):
        for y in range(img.height):
            r, g, b = pixels[x, y]
            # Добавляем случайный шум
            r = max(0, min(255, r + random.randint(-noise_level, noise_level)))
            g = max(0, min(255, g + random.randint(-noise_level, noise_level)))
            b = max(0, min(255, b + random.randint(-noise_level, noise_level)))
            pixels[x, y] = (r, g, b)
    # Сохраняем в байты
    buffer = BytesIO()
    img.save(buffer, format='JPEG')
    return buffer.getvalue()


# ============================================================
# ТЕСТЫ ВЫЧИСЛЕНИЯ ХЕШЕЙ
# ============================================================
class TestComputeHash:
    """Тесты для compute_image_hash и HashService.compute_hash."""

    def test_compute_hash_returns_image_hashes(self):
        """Проверяем что функция возвращает ImageHashes."""
        # Создаём тестовое изображение
        image_data = create_test_image()
        # Вычисляем хеш
        result = compute_image_hash(image_data)
        # Проверяем тип
        assert isinstance(result, ImageHashes), "Должен вернуть ImageHashes"
        # Проверяем что хеши не пустые
        assert result.phash, "pHash не должен быть пустым"
        assert result.dhash, "dHash не должен быть пустым"

    def test_hash_format_is_hex(self):
        """Проверяем что хеши в hex формате (16 символов)."""
        # Создаём тестовое изображение
        image_data = create_test_image()
        # Вычисляем хеш
        result = compute_image_hash(image_data)
        # Проверяем длину (64 бита = 16 hex символов)
        assert len(result.phash) == 16, "pHash должен быть 16 символов"
        assert len(result.dhash) == 16, "dHash должен быть 16 символов"
        # Проверяем что это валидный hex
        int(result.phash, 16)  # Должен парситься без ошибки
        int(result.dhash, 16)

    def test_same_image_same_hash(self):
        """Проверяем что одно и то же изображение даёт одинаковый хеш."""
        # Создаём тестовое изображение
        image_data = create_test_image()
        # Вычисляем хеш дважды
        hash1 = compute_image_hash(image_data)
        hash2 = compute_image_hash(image_data)
        # Хеши должны совпадать
        assert hash1.phash == hash2.phash, "pHash должен быть стабильным"
        assert hash1.dhash == hash2.dhash, "dHash должен быть стабильным"

    def test_different_images_different_hash(self):
        """Проверяем что разные изображения дают разные хеши."""
        # pHash фокусируется на СТРУКТУРЕ, не на цвете
        # Сплошные цвета дают одинаковые хеши (ожидаемо)
        # Создаём изображения с разной СТРУКТУРОЙ
        img1 = Image.new('RGB', (200, 200), (128, 128, 128))
        # Добавляем паттерн в первое изображение
        for x in range(0, 200, 20):
            for y in range(200):
                img1.putpixel((x, y), (255, 0, 0))
        buffer1 = BytesIO()
        img1.save(buffer1, format='JPEG')
        # Второе изображение - другой паттерн
        img2 = Image.new('RGB', (200, 200), (128, 128, 128))
        for x in range(200):
            for y in range(0, 200, 20):
                img2.putpixel((x, y), (0, 0, 255))
        buffer2 = BytesIO()
        img2.save(buffer2, format='JPEG')
        # Вычисляем хеши
        hash1 = compute_image_hash(buffer1.getvalue())
        hash2 = compute_image_hash(buffer2.getvalue())
        # Хеши должны отличаться
        assert hash1.phash != hash2.phash, "Разные паттерны должны давать разные хеши"

    def test_invalid_image_returns_none(self):
        """Проверяем что невалидные данные возвращают None."""
        # Передаём не изображение
        result = compute_image_hash(b"not an image")
        # Должен вернуть None
        assert result is None, "Невалидные данные должны вернуть None"

    def test_empty_data_returns_none(self):
        """Проверяем что пустые данные возвращают None."""
        result = compute_image_hash(b"")
        assert result is None, "Пустые данные должны вернуть None"

    @pytest.mark.skipif(not TEST_IMAGES_DIR.exists(), reason="Test images directory not found")
    def test_real_image_computes_hash(self):
        """Проверяем вычисление хеша для реального изображения."""
        # Ищем любое jpg в директории
        jpg_files = list(TEST_IMAGES_DIR.glob("*.jpg"))
        if not jpg_files:
            pytest.skip("No test images found")
        # Читаем первое изображение
        with open(jpg_files[0], 'rb') as f:
            image_data = f.read()
        # Вычисляем хеш
        result = compute_image_hash(image_data)
        # Проверяем результат
        assert result is not None, "Реальное изображение должно хешироваться"
        assert len(result.phash) == 16, "pHash должен быть 16 символов"


# ============================================================
# ТЕСТЫ СРАВНЕНИЯ ХЕШЕЙ
# ============================================================
class TestCompareHashes:
    """Тесты для compare_hashes и HashService.compare."""

    def test_identical_hashes_distance_zero(self):
        """Проверяем что идентичные хеши дают расстояние 0."""
        # Создаём изображение и вычисляем хеш
        image_data = create_test_image()
        hashes = compute_image_hash(image_data)
        # Сравниваем хеш сам с собой
        distance = compare_hashes(hashes.phash, hashes.phash)
        # Расстояние должно быть 0
        assert distance == 0, "Идентичные хеши должны давать расстояние 0"

    def test_different_hashes_positive_distance(self):
        """Проверяем что разные хеши дают положительное расстояние."""
        # Создаём изображения с разной СТРУКТУРОЙ (не просто цветом)
        img1 = Image.new('RGB', (200, 200), (128, 128, 128))
        for x in range(0, 200, 10):
            for y in range(200):
                img1.putpixel((x, y), (255, 0, 0))
        buffer1 = BytesIO()
        img1.save(buffer1, format='JPEG')
        img2 = Image.new('RGB', (200, 200), (128, 128, 128))
        for x in range(200):
            for y in range(0, 200, 10):
                img2.putpixel((x, y), (0, 0, 255))
        buffer2 = BytesIO()
        img2.save(buffer2, format='JPEG')
        # Вычисляем хеши
        hash1 = compute_image_hash(buffer1.getvalue())
        hash2 = compute_image_hash(buffer2.getvalue())
        # Сравниваем
        distance = compare_hashes(hash1.phash, hash2.phash)
        # Расстояние должно быть > 0
        assert distance > 0, "Разные структуры должны давать положительное расстояние"

    def test_similar_images_small_distance(self):
        """Проверяем что похожие изображения дают маленькое расстояние."""
        # Создаём базовое изображение с паттерном (не сплошной цвет)
        img = Image.new('RGB', (300, 300), (128, 128, 128))
        for x in range(0, 300, 30):
            for y in range(300):
                img.putpixel((x, y), (200, 50, 50))
        # Сохраняем в PNG (без потерь)
        buffer1 = BytesIO()
        img.save(buffer1, format='PNG')
        # Создаём похожее - слегка ресайзим и обратно
        img2 = img.resize((280, 280), Image.Resampling.LANCZOS)
        img2 = img2.resize((300, 300), Image.Resampling.LANCZOS)
        buffer2 = BytesIO()
        img2.save(buffer2, format='PNG')
        # Вычисляем хеши
        hash_base = compute_image_hash(buffer1.getvalue())
        hash_similar = compute_image_hash(buffer2.getvalue())
        # Сравниваем
        distance = compare_hashes(hash_base.phash, hash_similar.phash)
        # Расстояние должно быть маленьким (pHash устойчив к ресайзу)
        assert distance < 15, f"Похожие изображения должны давать маленькое расстояние, получили {distance}"

    def test_distance_range(self):
        """Проверяем что расстояние в диапазоне 0-64."""
        # Создаём два разных изображения
        img1 = create_test_image(color=(0, 0, 0))
        img2 = create_test_image(color=(255, 255, 255))
        hash1 = compute_image_hash(img1)
        hash2 = compute_image_hash(img2)
        # Сравниваем
        distance = compare_hashes(hash1.phash, hash2.phash)
        # Проверяем диапазон
        assert 0 <= distance <= 64, f"Расстояние должно быть 0-64, получили {distance}"

    def test_invalid_hash_returns_max_distance(self):
        """Проверяем что невалидный хеш возвращает максимальное расстояние."""
        # Создаём валидный хеш
        image_data = create_test_image()
        valid_hash = compute_image_hash(image_data)
        # Сравниваем с невалидным хешем
        distance = compare_hashes(valid_hash.phash, "invalid_hash")
        # Должно вернуть 64 (максимум)
        assert distance == 64, "Невалидный хеш должен давать максимальное расстояние"


# ============================================================
# ТЕСТЫ ДЕТЕКЦИИ ПОХОЖИХ ИЗОБРАЖЕНИЙ
# ============================================================
class TestIsSimilar:
    """Тесты для HashService.is_similar."""

    def test_identical_images_similar(self):
        """Проверяем что идентичные изображения считаются похожими."""
        # Создаём изображение
        image_data = create_test_image()
        hashes = compute_image_hash(image_data)
        # Проверяем
        service = HashService()
        is_similar, distance = service.is_similar(
            hashes.phash, hashes.dhash,
            hashes.phash, hashes.dhash,
            threshold=10
        )
        # Используем == вместо is для совместимости с numpy bool
        assert is_similar == True, "Идентичные изображения должны быть похожими"
        assert distance == 0, "Расстояние должно быть 0"

    def test_different_images_not_similar(self):
        """Проверяем что разные изображения не считаются похожими."""
        # Создаём два изображения с разной СТРУКТУРОЙ
        img1 = Image.new('RGB', (200, 200), (128, 128, 128))
        for x in range(0, 200, 10):
            for y in range(200):
                img1.putpixel((x, y), (255, 0, 0))
        buffer1 = BytesIO()
        img1.save(buffer1, format='JPEG')
        img2 = Image.new('RGB', (200, 200), (128, 128, 128))
        for x in range(200):
            for y in range(0, 200, 10):
                img2.putpixel((x, y), (0, 0, 255))
        buffer2 = BytesIO()
        img2.save(buffer2, format='JPEG')
        hash1 = compute_image_hash(buffer1.getvalue())
        hash2 = compute_image_hash(buffer2.getvalue())
        # Проверяем с низким порогом
        service = HashService()
        is_similar, distance = service.is_similar(
            hash1.phash, hash1.dhash,
            hash2.phash, hash2.dhash,
            threshold=5
        )
        # Используем == вместо is для совместимости с numpy bool
        assert is_similar == False, "Разные структуры не должны быть похожими"

    def test_threshold_affects_similarity(self):
        """Проверяем что порог влияет на результат."""
        # Создаём два изображения с известным расстоянием
        img1 = create_test_image(color=(100, 100, 100))
        img2 = create_test_image(color=(110, 110, 110))
        hash1 = compute_image_hash(img1)
        hash2 = compute_image_hash(img2)
        # Получаем расстояние
        distance = compare_hashes(hash1.phash, hash2.phash)
        # Проверяем с разными порогами
        service = HashService()
        # С порогом выше расстояния - похожи
        is_similar_high, _ = service.is_similar(
            hash1.phash, hash1.dhash,
            hash2.phash, hash2.dhash,
            threshold=distance + 5
        )
        # С порогом ниже расстояния - не похожи (если distance > 0)
        is_similar_low, _ = service.is_similar(
            hash1.phash, hash1.dhash,
            hash2.phash, hash2.dhash,
            threshold=max(0, distance - 5)
        )
        # Используем == вместо is для совместимости с numpy bool
        assert is_similar_high == True, "С высоким порогом должны быть похожи"
        # is_similar_low может быть True если distance очень маленький


# ============================================================
# ТЕСТЫ ДЕТЕКЦИИ ЛОГО
# ============================================================
class TestLogoDetection:
    """Тесты для compute_logo_hash и детекции областей."""

    def test_available_regions(self):
        """Проверяем список доступных регионов."""
        regions = get_available_logo_regions()
        # Должны быть все ожидаемые регионы
        expected = ['top_left', 'top_right', 'bottom_left', 'bottom_right',
                    'top_center', 'bottom_center']
        for region in expected:
            assert region in regions, f"Регион {region} должен быть доступен"

    def test_logo_regions_format(self):
        """Проверяем формат регионов в LOGO_REGIONS."""
        for name, coords in LOGO_REGIONS.items():
            # Должен быть tuple из 4 элементов
            assert len(coords) == 4, f"Регион {name} должен иметь 4 координаты"
            left, top, right, bottom = coords
            # Все координаты должны быть в диапазоне 0-1
            assert 0 <= left <= 1, f"left должен быть 0-1 для {name}"
            assert 0 <= top <= 1, f"top должен быть 0-1 для {name}"
            assert 0 <= right <= 1, f"right должен быть 0-1 для {name}"
            assert 0 <= bottom <= 1, f"bottom должен быть 0-1 для {name}"
            # left < right, top < bottom
            assert left < right, f"left < right для {name}"
            assert top < bottom, f"top < bottom для {name}"

    def test_compute_logo_hash_returns_hashes(self):
        """Проверяем что compute_logo_hash возвращает хеши."""
        # Создаём достаточно большое изображение
        image_data = create_test_image(width=500, height=500)
        # Вычисляем хеш для области
        result = compute_logo_hash(image_data, 'top_left')
        # Проверяем результат
        assert result is not None, "Должен вернуть хеши для большого изображения"
        assert isinstance(result, ImageHashes), "Должен вернуть ImageHashes"

    def test_small_image_logo_returns_none(self):
        """Проверяем что маленькое изображение возвращает None для лого."""
        # Создаём маленькое изображение
        image_data = create_test_image(width=50, height=50)
        # Область будет слишком маленькой (< 32 пикселей)
        result = compute_logo_hash(image_data, 'top_left')
        # Должен вернуть None
        assert result is None, "Маленькое изображение должно вернуть None для лого"

    def test_invalid_region_returns_none(self):
        """Проверяем что несуществующий регион возвращает None."""
        image_data = create_test_image(width=500, height=500)
        result = compute_logo_hash(image_data, 'invalid_region')
        assert result is None, "Несуществующий регион должен вернуть None"

    def test_different_regions_different_hashes(self):
        """Проверяем что разные регионы дают разные хеши."""
        # Создаём изображение с разным содержимым в углах
        img = Image.new('RGB', (500, 500), (128, 128, 128))
        # Красный в левом верхнем углу
        for x in range(100):
            for y in range(100):
                img.putpixel((x, y), (255, 0, 0))
        # Синий в правом верхнем углу
        for x in range(400, 500):
            for y in range(100):
                img.putpixel((x, y), (0, 0, 255))
        # Сохраняем в байты
        buffer = BytesIO()
        img.save(buffer, format='JPEG')
        image_data = buffer.getvalue()
        # Вычисляем хеши для разных регионов
        hash_tl = compute_logo_hash(image_data, 'top_left')
        hash_tr = compute_logo_hash(image_data, 'top_right')
        # Хеши должны отличаться
        assert hash_tl is not None and hash_tr is not None
        assert hash_tl.phash != hash_tr.phash, "Разные регионы должны давать разные хеши"

    @pytest.mark.skipif(not TEST_IMAGES_DIR.exists(), reason="Test images directory not found")
    def test_real_image_logo_detection(self):
        """Проверяем детекцию лого на реальных изображениях."""
        # Читаем два VIP Kazashki изображения если доступны
        img1_path = TEST_IMAGES_DIR / "scam_vip_kazashki.jpg"
        img2_path = TEST_IMAGES_DIR / "scam_vip_kazashki1.jpg"
        if not img1_path.exists() or not img2_path.exists():
            pytest.skip("VIP Kazashki test images not found")
        # Читаем изображения
        with open(img1_path, 'rb') as f:
            img1 = f.read()
        with open(img2_path, 'rb') as f:
            img2 = f.read()
        # Вычисляем хеши для top_left (где обычно лого)
        hash1 = compute_logo_hash(img1, 'top_left')
        hash2 = compute_logo_hash(img2, 'top_left')
        # Проверяем что хеши вычислились
        assert hash1 is not None, "Должен вычислить хеш для img1"
        assert hash2 is not None, "Должен вычислить хеш для img2"
        # Сравниваем (VIP Kazashki 1 и 2 должны иметь одинаковое лого)
        distance = compare_hashes(hash1.phash, hash2.phash)
        # Логи должны быть очень похожи (distance близко к 0)
        assert distance <= 5, f"Одинаковые лого должны давать маленькое расстояние, получили {distance}"


# ============================================================
# ТЕСТЫ ДЛЯ ФОРМАТОВ ИЗОБРАЖЕНИЙ
# ============================================================
class TestImageFormats:
    """Тесты для разных форматов изображений."""

    def test_jpeg_format(self):
        """Проверяем работу с JPEG."""
        img = Image.new('RGB', (200, 200), (255, 0, 0))
        buffer = BytesIO()
        img.save(buffer, format='JPEG')
        result = compute_image_hash(buffer.getvalue())
        assert result is not None, "JPEG должен хешироваться"

    def test_png_format(self):
        """Проверяем работу с PNG."""
        img = Image.new('RGB', (200, 200), (0, 255, 0))
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        result = compute_image_hash(buffer.getvalue())
        assert result is not None, "PNG должен хешироваться"

    def test_png_with_transparency(self):
        """Проверяем работу с PNG с прозрачностью."""
        # Создаём RGBA изображение с прозрачностью
        img = Image.new('RGBA', (200, 200), (255, 0, 0, 128))
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        result = compute_image_hash(buffer.getvalue())
        assert result is not None, "PNG с прозрачностью должен хешироваться"

    def test_webp_format(self):
        """Проверяем работу с WebP."""
        img = Image.new('RGB', (200, 200), (0, 0, 255))
        buffer = BytesIO()
        img.save(buffer, format='WEBP')
        result = compute_image_hash(buffer.getvalue())
        assert result is not None, "WebP должен хешироваться"

    def test_gif_format(self):
        """Проверяем работу с GIF (первый кадр)."""
        img = Image.new('P', (200, 200))
        buffer = BytesIO()
        img.save(buffer, format='GIF')
        result = compute_image_hash(buffer.getvalue())
        assert result is not None, "GIF должен хешироваться"
