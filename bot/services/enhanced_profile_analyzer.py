"""
Расширенный анализатор профиля пользователя
Интегрирует анализ возраста аккаунта по ID и проверку био на подозрительный контент
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone

from bot.services.account_age_estimator import account_age_estimator
from bot.services.bio_content_analyzer import bio_analyzer

logger = logging.getLogger(__name__)

class EnhancedProfileAnalyzer:
    """Расширенный анализатор профиля пользователя"""
    
    def __init__(self):
        """Инициализация анализатора"""
        self.age_estimator = account_age_estimator
        self.bio_analyzer = bio_analyzer
    
    async def analyze_user_profile_enhanced(self, user_data: dict, bot=None) -> Dict[str, Any]:
        """
        УПРОЩЕННЫЙ анализ профиля пользователя - ТОЛЬКО по возрасту аккаунта

        ВАЖНО: Проверяется ТОЛЬКО возраст аккаунта <= 30 дней
        Все остальные проверки (био, username, имя и т.д.) ОТКЛЮЧЕНЫ

        Args:
            user_data: Данные пользователя
            bot: Экземпляр бота (не используется, оставлен для совместимости)

        Returns:
            Словарь с результатами анализа
        """
        analysis = {
            "is_suspicious": False,
            "reasons": [],
            "risk_score": 0,
            "age_analysis": {},
            "bio_analysis": {},
            "profile_analysis": {}
        }

        user_id = user_data.get("id", "unknown")

        if user_id == "unknown":
            logger.warning("Неизвестный user_id для анализа профиля")
            analysis["risk_score"] = 0
            analysis["reasons"].append("Неизвестный user_id")
            return analysis

        try:
            # ТОЛЬКО анализ возраста аккаунта по ID
            age_analysis = self._analyze_account_age(user_id)
            analysis["age_analysis"] = age_analysis
            analysis["risk_score"] = age_analysis["risk_score"]

            if age_analysis["is_suspicious"]:
                analysis["is_suspicious"] = True
                analysis["reasons"].extend(age_analysis["reasons"])

            # Логируем результаты
            self._log_analysis_results(user_id, analysis)

        except Exception as e:
            logger.error(f"Ошибка при анализе профиля пользователя {user_id}: {e}")
            analysis["risk_score"] = 0
            analysis["reasons"].append("Ошибка анализа профиля")

        return analysis
    
    def _analyze_account_age(self, user_id: int) -> Dict[str, Any]:
        """
        Анализирует возраст аккаунта по user_id

        ПРАВИЛО: Если возраст аккаунта <= 30 дней → МУТ (100 баллов, is_suspicious = True)

        Args:
            user_id: ID пользователя

        Returns:
            Результаты анализа возраста
        """
        try:
            age_info = self.age_estimator.get_detailed_age_info(user_id)
            age_days = age_info["age_days"]

            # УПРОЩЕННАЯ ЛОГИКА: Только возраст <= 30 дней = МУТ
            # ВАЖНО: Проверяем age_days >= 0, чтобы отрицательные значения не проходили
            is_suspicious = 0 <= age_days <= 30
            risk_score = 100 if is_suspicious else 0

            analysis = {
                "is_suspicious": is_suspicious,
                "reasons": [],
                "risk_score": risk_score,
                "age_days": age_days,
                "creation_date": age_info["creation_date_str"],
                "risk_label": "young" if is_suspicious else "mature",
                "risk_description": f"Аккаунт {age_days} дней - {'МУТИМ' if is_suspicious else 'в порядке'}"
            }

            if is_suspicious:
                analysis["reasons"].append(f"Аккаунт слишком молодой: {age_days} дней (порог: ≤30)")

            logger.info(f"   📅 АНАЛИЗ ВОЗРАСТА АККАУНТА:")
            logger.info(f"   📅 Предполагаемая дата создания: {age_info['creation_date_str']}")
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
                "risk_description": "Ошибка анализа возраста"
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
        
        Args:
            user_id: ID пользователя
            analysis: Результаты анализа
        """
        logger.info(f"   📊 ИТОГОВЫЙ РЕЗУЛЬТАТ РАСШИРЕННОГО АНАЛИЗА:")
        logger.info(f"   🎯 Общий балл риска: {analysis['risk_score']}/100")
        logger.info(f"   🚨 Подозрительный: {analysis['is_suspicious']}")
        
        if analysis['reasons']:
            logger.info(f"   ⚠️ Причины подозрительности:")
            for reason in analysis['reasons']:
                logger.info(f"      - {reason}")
        
        # Детализация по категориям
        if analysis['age_analysis'].get('risk_score', 0) > 0:
            logger.info(f"   📅 Возраст аккаунта: {analysis['age_analysis']['risk_score']} баллов")
        
        if analysis['bio_analysis'].get('risk_score', 0) > 0:
            logger.info(f"   📝 Био: {analysis['bio_analysis']['risk_score']} баллов")
        
        if analysis['profile_analysis'].get('risk_score', 0) > 0:
            logger.info(f"   👤 Профиль: {analysis['profile_analysis']['risk_score']} баллов")

# Глобальный экземпляр для использования в других модулях
enhanced_profile_analyzer = EnhancedProfileAnalyzer()
