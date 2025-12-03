"""
Расширенный анализатор профиля пользователя
Интегрирует анализ возраста аккаунта по ID и проверку био на подозрительный контент

ОБНОВЛЕНО: Добавлена проверка через Pyrogram (MTProto API):
- Точная проверка возраста аккаунта (<30 дней → МУТ)
- Проверка дат загрузки ВСЕХ фото профиля (если ВСЕ <15 дней → МУТ)
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone

from bot.services.account_age_estimator import account_age_estimator
from bot.services.bio_content_analyzer import bio_analyzer

# ============================================================
# ИМПОРТ PYROGRAM СЕРВИСА для расширенной проверки профиля
# ============================================================
# Pyrogram позволяет получить данные, недоступные через Bot API:
# - Точная дата создания аккаунта
# - Даты загрузки фото профиля
from bot.services.pyrogram_client import pyrogram_service

logger = logging.getLogger(__name__)

class EnhancedProfileAnalyzer:
    """Расширенный анализатор профиля пользователя"""
    
    def __init__(self):
        """Инициализация анализатора"""
        self.age_estimator = account_age_estimator
        self.bio_analyzer = bio_analyzer
    
    async def analyze_user_profile_enhanced(self, user_data: dict, bot=None) -> Dict[str, Any]:
        """
        РАСШИРЕННЫЙ анализ профиля пользователя через Pyrogram (MTProto API)

        ПРОВЕРКИ:
        1. Возраст аккаунта <= 30 дней → МУТ (100 баллов)
        2. ВСЕ фото моложе 15 дней → МУТ (100 баллов)

        ЛОГИКА МУТА:
        - Если хотя бы ОДНА проверка вернула is_suspicious = True → МУТ
        - Общий балл риска = МАКСИМУМ из баллов всех проверок

        Args:
            user_data: Данные пользователя
            bot: Экземпляр бота (не используется, оставлен для совместимости)

        Returns:
            Словарь с результатами анализа:
            {
                "is_suspicious": bool,  # True если нужен МУТ
                "reasons": list,        # Причины для мута
                "risk_score": int,      # Общий балл риска (0-100)
                "age_analysis": dict,   # Результаты проверки возраста
                "photos_analysis": dict,  # Результаты проверки фото (НОВОЕ!)
                "bio_analysis": dict,   # Результаты проверки био
                "profile_analysis": dict  # Результаты проверки профиля
            }
        """
        # Инициализируем структуру результатов анализа
        analysis = {
            "is_suspicious": False,  # Флаг: нужен ли мут
            "reasons": [],           # Список причин для мута
            "risk_score": 0,         # Общий балл риска
            "age_analysis": {},      # Результаты проверки возраста
            "photos_analysis": {},   # Результаты проверки фото (НОВОЕ!)
            "bio_analysis": {},      # Результаты проверки био
            "profile_analysis": {}   # Результаты проверки профиля
        }

        # Получаем ID пользователя из данных
        user_id = user_data.get("id", "unknown")

        # Проверка корректности ID
        if user_id == "unknown":
            logger.warning("Неизвестный user_id для анализа профиля")
            analysis["risk_score"] = 0
            analysis["reasons"].append("Неизвестный user_id")
            return analysis

        try:
            # ============================================================
            # ПРОВЕРКА #1: Возраст аккаунта (приблизительная оценка по ID)
            # ============================================================
            # Используем старый метод для совместимости
            # Правило: Если возраст <= 30 дней → is_suspicious = True, risk_score = 100
            age_analysis = await self._analyze_account_age(user_id)
            analysis["age_analysis"] = age_analysis

            # Если возраст подозрительный → обновляем общий анализ
            if age_analysis["is_suspicious"]:
                analysis["is_suspicious"] = True  # Ставим флаг мута
                analysis["reasons"].extend(age_analysis["reasons"])  # Добавляем причины
                analysis["risk_score"] = max(analysis["risk_score"], age_analysis["risk_score"])  # Обновляем балл

            # ============================================================
            # ПРОВЕРКА #2: ВСЕ фото профиля через Pyrogram (НОВОЕ!)
            # ============================================================
            # Используем Pyrogram для получения дат фото (недоступно через Bot API)
            # Правило: Если ВСЕ фото моложе 15 дней → is_suspicious = True, risk_score = 100
            photos_analysis = await self._analyze_profile_photos_pyrogram(user_id)
            analysis["photos_analysis"] = photos_analysis

            # Если фото подозрительные → обновляем общий анализ
            if photos_analysis["is_suspicious"]:
                analysis["is_suspicious"] = True  # Ставим флаг мута
                analysis["reasons"].extend(photos_analysis["reasons"])  # Добавляем причины
                analysis["risk_score"] = max(analysis["risk_score"], photos_analysis["risk_score"])  # Обновляем балл

            # ============================================================
            # ЛОГИРОВАНИЕ РЕЗУЛЬТАТОВ
            # ============================================================
            # Выводим итоговый результат всех проверок
            self._log_analysis_results(user_id, analysis)

        except Exception as e:
            # Обработка ошибок: если анализ не удался, не мутим пользователя
            logger.error(f"Ошибка при анализе профиля пользователя {user_id}: {e}")
            analysis["risk_score"] = 0
            analysis["is_suspicious"] = False  # НЕ мутим при ошибке
            analysis["reasons"].append("Ошибка анализа профиля")

        return analysis
    
    async def _analyze_account_age(self, user_id: int) -> Dict[str, Any]:
        """
        Анализирует возраст аккаунта по user_id.

        Источники данных:
        1) Приблизительная оценка по user_id через AccountAgeEstimator
        2) ТОЧНАЯ (насколько это возможно) оценка через Pyrogram по дате самого старого фото

        ПРАВИЛО: Если возраст аккаунта <= 30 дней → МУТ (100 баллов, is_suspicious = True)

        Args:
            user_id: ID пользователя

        Returns:
            Результаты анализа возраста
        """
        try:
            # Базовая оценка по user_id (старый метод)
            age_info = self.age_estimator.get_detailed_age_info(user_id)
            age_days = age_info["age_days"]
            creation_date_str = age_info["creation_date_str"]

            # Попытка уточнить возраст через Pyrogram (если доступен)
            precise_age_info: Optional[Dict[str, Any]] = None
            if pyrogram_service.is_available():
                try:
                    precise_age_info = await pyrogram_service.get_account_age(user_id)
                except Exception as e:
                    logger.warning(f"⚠️ Ошибка получения точного возраста аккаунта через Pyrogram для {user_id}: {e}")
                    precise_age_info = None

            if precise_age_info and precise_age_info.get("account_age_days") is not None:
                precise_age_days = precise_age_info["account_age_days"]
                if precise_age_days is not None:
                    # Защищаемся от отрицательных значений
                    if precise_age_days < 0:
                        logger.warning(
                            f"⚠️ Обнаружен отрицательный точный возраст аккаунта (age_days={precise_age_days}) для {user_id}, "
                            "принудительно устанавливаем 0."
                        )
                        precise_age_days = 0
                    age_days = precise_age_days

                # Если Pyrogram вернул дату создания - используем её для логов
                creation_dt = precise_age_info.get("creation_date")
                if isinstance(creation_dt, datetime):
                    try:
                        creation_date_str = creation_dt.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
                    except Exception:
                        creation_date_str = creation_dt.strftime('%Y-%m-%d %H:%M:%S')

            # УПРОЩЕННАЯ ЛОГИКА: Только возраст <= 30 дней = МУТ
            # ВАЖНО: Проверяем age_days >= 0, чтобы отрицательные значения не проходили
            is_suspicious = isinstance(age_days, int) and 0 <= age_days <= 30
            risk_score = 100 if is_suspicious else 0

            analysis = {
                "is_suspicious": is_suspicious,
                "reasons": [],
                "risk_score": risk_score,
                "age_days": age_days,
                "creation_date": creation_date_str,
                "risk_label": "young" if is_suspicious else "mature",
                "risk_description": f"Аккаунт {age_days} дней - {'МУТИМ' if is_suspicious else 'в порядке'}",
            }

            if is_suspicious:
                analysis["reasons"].append(f"Аккаунт слишком молодой: {age_days} дней (порог: ≤30)")

            logger.info("   📅 АНАЛИЗ ВОЗРАСТА АККАУНТА:")
            logger.info(f"   📅 Предполагаемая дата создания: {creation_date_str}")
            logger.info(f"   ⏰ Возраст аккаунта: {age_days} дней")
            logger.info(f"   🎯 Балл риска: {risk_score}/100 ({'МУТИМ' if is_suspicious else 'НЕ МУТИМ'})")

            return analysis

        except Exception as e:
            logger.error(f"Ошибка анализа возраста аккаунта {user_id}: {e}")
            return {
                "is_suspicious": False,
                "reasons": ["Ошибка анализа возраста"],
                "risk_score": 0,
                "age_days": "неизвестно",
                "creation_date": "неизвестно",
                "risk_label": "unknown",
                "risk_description": "Ошибка анализа возраста",
            }

    async def _analyze_profile_photos_pyrogram(self, user_id: int) -> Dict[str, Any]:
        """
        Анализирует ВСЕ фото профиля пользователя через Pyrogram (MTProto API)

        ПРАВИЛО: Если ВСЕ фото моложе 15 дней → МУТ (100 баллов, is_suspicious = True)

        ЛОГИКА (по требованию):
        - Если ВСЕ фото моложе 15 дней → ПОДОЗРИТЕЛЬНО (МУТ)
        - Если хотя бы ОДНО фото старше 15 дней → НЕ ПОДОЗРИТЕЛЬНО (ПРОПУСК)
        - Если фото нет вообще → НЕ ПОДОЗРИТЕЛЬНО (ПРОПУСК)

        Args:
            user_id: ID пользователя

        Returns:
            Результаты анализа фото:
            {
                "is_suspicious": bool,  # True если ВСЕ фото моложе 15 дней
                "reasons": list,        # Причины подозрительности
                "risk_score": int,      # Оценка риска (100 если подозрительно, 0 если нет)
                "photos_count": int,    # Количество фото в профиле
                "youngest_photo_days": int,  # Возраст самого нового фото
                "oldest_photo_days": int,    # Возраст самого старого фото
                "all_photos_young": bool,    # Флаг: ВСЕ ли фото молодые
                "photos_details": str   # Детальная информация для логов
            }
        """
        try:
            # ВАЖНО: Проверяем, доступен ли Pyrogram клиент
            # Если Pyrogram не настроен (нет API_ID/API_HASH), пропускаем проверку
            is_available = pyrogram_service.is_available()
            logger.info(f"   📸 ПРОВЕРКА ФОТО ПРОФИЛЯ: Pyrogram доступен = {is_available}")
            if not is_available:
                logger.warning(f"   ⚠️ PYROGRAM НЕДОСТУПЕН! Проверка фото пропущена для пользователя {user_id}")
                logger.warning(f"   ⚠️ Убедитесь, что Pyrogram был инициализирован при старте бота")
                return {
                    "is_suspicious": False,  # НЕ считаем подозрительным, если не можем проверить
                    "reasons": [],
                    "risk_score": 0,
                    "photos_count": 0,
                    "youngest_photo_days": None,
                    "oldest_photo_days": None,
                    "all_photos_young": False,
                    "photos_details": "Pyrogram недоступен"
                }

            # Получаем информацию о ВСЕХ фото через Pyrogram
            # Эта функция возвращает данные о фото, недоступные через Bot API
            photos_check = await pyrogram_service.check_all_photos_young(
                user_id=user_id,
                max_age_days=15  # Порог: 15 дней
            )

            # Извлекаем данные из результата проверки
            all_photos_young = photos_check['all_photos_young']  # ВСЕ ли фото моложе 15 дней?
            photos_count = photos_check['photos_count']  # Сколько всего фото
            youngest_photo_days = photos_check['youngest_photo_days']  # Самое новое фото
            oldest_photo_days = photos_check['oldest_photo_days']  # Самое старое фото
            reason = photos_check['reason']  # Причина для логов

            # Определяем, подозрительно ли это
            is_suspicious = all_photos_young  # Если ВСЕ фото молодые → подозрительно
            risk_score = 100 if is_suspicious else 0  # Максимальный риск если подозрительно

            # Формируем список причин для логов
            reasons = []
            if is_suspicious:
                reasons.append(f"ВСЕ фото профиля моложе 15 дней: {reason}")

            # Формируем детальную информацию для логов
            if photos_count == 0:
                photos_details = "Нет фото в профиле"
            elif photos_count == 1:
                photos_details = f"1 фото: {oldest_photo_days} дней назад"
            else:
                photos_details = f"{photos_count} фото: от {youngest_photo_days} до {oldest_photo_days} дней"

            # Логируем результаты проверки
            logger.info(f"   📸 ПРОВЕРКА ФОТО ПРОФИЛЯ (Pyrogram):")
            logger.info(f"   📸 Всего фото: {photos_count}")
            if photos_count > 0:
                logger.info(f"   📸 Самое новое: {youngest_photo_days} дней назад")
                logger.info(f"   📸 Самое старое: {oldest_photo_days} дней назад")
                logger.info(f"   📸 Все фото моложе 15 дней: {all_photos_young}")
            logger.info(f"   🎯 Балл риска: {risk_score}/100 ({'МУТИМ' if is_suspicious else 'НЕ МУТИМ'})")
            logger.info(f"   📝 Причина: {reason}")

            return {
                "is_suspicious": is_suspicious,
                "reasons": reasons,
                "risk_score": risk_score,
                "photos_count": photos_count,
                "youngest_photo_days": youngest_photo_days,
                "oldest_photo_days": oldest_photo_days,
                "all_photos_young": all_photos_young,
                "photos_details": photos_details
            }

        except Exception as e:
            # Обработка ошибок: если проверка не удалась, не считаем это подозрительным
            logger.error(f"Ошибка анализа фото профиля для {user_id}: {e}")
            return {
                "is_suspicious": False,  # НЕ мутим при ошибке
                "reasons": ["Ошибка проверки фото"],
                "risk_score": 0,
                "photos_count": 0,
                "youngest_photo_days": None,
                "oldest_photo_days": None,
                "all_photos_young": False,
                "photos_details": f"Ошибка: {str(e)}"
            }

    async def _analyze_user_bio(self, user_data: dict, bot=None) -> Dict[str, Any]:
        """
        Анализирует био пользователя на подозрительный контент
        
        Args:
            user_data: Данные пользователя
            bot: Экземпляр бота
            
        Returns:
            Результаты анализа био
        """
        try:
            # Пытаемся получить био через API
            bio_text = ""
            if bot and user_data.get("id"):
                try:
                    user_chat = await bot.get_chat(user_data["id"])
                    if hasattr(user_chat, 'bio') and user_chat.bio:
                        bio_text = user_chat.bio
                except Exception as e:
                    logger.warning(f"Не удалось получить био пользователя {user_data.get('id')}: {e}")
            
            # Анализируем био
            bio_analysis = self.bio_analyzer.analyze_bio_content(bio_text)
            
            logger.info(f"   📝 АНАЛИЗ БИО:")
            if bio_text:
                logger.info(f"   📝 Био: {bio_text[:100]}{'...' if len(bio_text) > 100 else ''}")
                logger.info(f"   🎯 Балл риска: {bio_analysis['risk_score']}/100")
                if bio_analysis['categories']:
                    logger.info(f"   ⚠️ Категории: {', '.join(bio_analysis['categories'])}")
                else:
                    logger.info(f"   ✅ Био в порядке")
            else:
                logger.info(f"   ℹ️ Био отсутствует (0 баллов)")
            
            return bio_analysis
            
        except Exception as e:
            logger.error(f"Ошибка анализа био пользователя {user_data.get('id')}: {e}")
            return {
                "is_suspicious": False,
                "reasons": [],
                "risk_score": 0,
                "categories": [],
                "matched_patterns": [],
                "reason": "Ошибка анализа био"
            }
    
    def _analyze_basic_profile(self, user_data: dict) -> Dict[str, Any]:
        """
        Базовый анализ профиля пользователя
        
        Args:
            user_data: Данные пользователя
            
        Returns:
            Результаты базового анализа
        """
        analysis = {
            "is_suspicious": False,
            "reasons": [],
            "risk_score": 0
        }
        
        # Проверяем наличие username
        if not user_data.get("username"):
            analysis["is_suspicious"] = True
            analysis["reasons"].append("Отсутствует username")
            analysis["risk_score"] += 15
            logger.warning(f"   ⚠️ НЕТ USERNAME (+15 баллов)")
        else:
            logger.info(f"   ✅ ЕСТЬ USERNAME (0 баллов)")
            
            # Анализируем username на подозрительность
            username = user_data.get("username", "").lower()
            suspicious_patterns = [
                "bot", "admin", "support", "help", "service", "official",
                "test", "demo", "sample", "example", "temp", "tmp"
            ]
            
            for pattern in suspicious_patterns:
                if pattern in username:
                    analysis["is_suspicious"] = True
                    analysis["reasons"].append(f"Подозрительный username содержит '{pattern}'")
                    analysis["risk_score"] += 10
                    logger.warning(f"   ⚠️ ПОДОЗРИТЕЛЬНЫЙ USERNAME: содержит '{pattern}' (+10 баллов)")
                    break
        
        # Проверяем наличие имени
        if not user_data.get("first_name"):
            analysis["is_suspicious"] = True
            analysis["reasons"].append("Отсутствует имя")
            analysis["risk_score"] += 20
            logger.warning(f"   ⚠️ НЕТ ИМЕНИ (+20 баллов)")
        else:
            logger.info(f"   ✅ ЕСТЬ ИМЯ (0 баллов)")
            
            # Анализируем имя на подозрительность
            first_name = user_data.get("first_name", "").lower()
            suspicious_names = [
                "bot", "admin", "support", "help", "service", "official",
                "test", "demo", "sample", "example", "temp", "tmp",
                "user", "member", "guest", "anonymous"
            ]
            
            for pattern in suspicious_names:
                if pattern in first_name:
                    analysis["is_suspicious"] = True
                    analysis["reasons"].append(f"Подозрительное имя содержит '{pattern}'")
                    analysis["risk_score"] += 10
                    logger.warning(f"   ⚠️ ПОДОЗРИТЕЛЬНОЕ ИМЯ: содержит '{pattern}' (+10 баллов)")
                    break
        
        # Проверяем язык
        language = user_data.get("language_code", "").lower()
        if language not in ["ru", "en", "uk", "be", "kk", "uz", "ky", "tg"]:
            analysis["risk_score"] += 5
            logger.info(f"   ℹ️ НЕСТАНДАРТНЫЙ ЯЗЫК: '{language}' (+5 баллов)")
        else:
            logger.info(f"   ✅ СТАНДАРТНЫЙ ЯЗЫК: '{language}' (0 баллов)")
        
        # Проверяем статус бота
        if user_data.get("is_bot", False):
            analysis["is_suspicious"] = True
            analysis["reasons"].append("Пользователь является ботом")
            analysis["risk_score"] += 50
            logger.warning(f"   🚨 ПОЛЬЗОВАТЕЛЬ - БОТ (+50 баллов)")
        else:
            logger.info(f"   ✅ НЕ БОТ (0 баллов)")
        
        # Проверяем Premium статус
        if user_data.get("is_premium", False):
            analysis["risk_score"] -= 5  # Premium пользователи менее подозрительны
            logger.info(f"   ⭐ PREMIUM ПОЛЬЗОВАТЕЛЬ (-5 баллов)")
        else:
            logger.info(f"   ℹ️ ОБЫЧНЫЙ ПОЛЬЗОВАТЕЛЬ (0 баллов)")
        
        return analysis
    
    def _log_analysis_results(self, user_id: int, analysis: Dict[str, Any]) -> None:
        """
        Логирует результаты анализа

        ОБНОВЛЕНО: Добавлено логирование результатов проверки фото через Pyrogram

        Args:
            user_id: ID пользователя
            analysis: Результаты анализа
        """
        logger.info(f"   📊 ИТОГОВЫЙ РЕЗУЛЬТАТ РАСШИРЕННОГО АНАЛИЗА:")
        logger.info(f"   🎯 Общий балл риска: {analysis['risk_score']}/100")
        logger.info(f"   🚨 Подозрительный: {analysis['is_suspicious']}")
        logger.info(f"   🚨 РЕШЕНИЕ: {'МУТИМ' if analysis['is_suspicious'] else 'НЕ МУТИМ'}")

        # Выводим причины подозрительности (если есть)
        if analysis['reasons']:
            logger.info(f"   ⚠️ Причины подозрительности:")
            for reason in analysis['reasons']:
                logger.info(f"      - {reason}")

        # ============================================================
        # ДЕТАЛИЗАЦИЯ ПО КАТЕГОРИЯМ ПРОВЕРОК
        # ============================================================

        # Проверка #1: Возраст аккаунта
        if analysis['age_analysis'].get('risk_score', 0) > 0:
            logger.info(f"   📅 Возраст аккаунта: {analysis['age_analysis']['risk_score']} баллов")

        # Проверка #2: Фото профиля (НОВОЕ!)
        if analysis.get('photos_analysis'):
            photos_data = analysis['photos_analysis']
            risk_score = photos_data.get('risk_score', 0)
            # Логируем даже если риск = 0 (для информации)
            logger.info(f"   📸 Фото профиля: {risk_score} баллов ({photos_data.get('photos_details', 'нет данных')})")

        # Проверка #3: Био
        if analysis['bio_analysis'].get('risk_score', 0) > 0:
            logger.info(f"   📝 Био: {analysis['bio_analysis']['risk_score']} баллов")

        # Проверка #4: Профиль
        if analysis['profile_analysis'].get('risk_score', 0) > 0:
            logger.info(f"   👤 Профиль: {analysis['profile_analysis']['risk_score']} баллов")

# Глобальный экземпляр для использования в других модулях
enhanced_profile_analyzer = EnhancedProfileAnalyzer()
