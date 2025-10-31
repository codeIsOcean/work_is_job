"""
Модуль для анализа био пользователя на подозрительный контент
Проверяет на наркотики, проституцию, спам и другие нарушения
"""

import re
import logging
from typing import List, Tuple, Dict, Optional

logger = logging.getLogger(__name__)

class BioContentAnalyzer:
    """Класс для анализа содержимого био пользователя"""
    
    def __init__(self):
        """Инициализация с загрузкой паттернов"""
        self.drug_patterns = self._load_drug_patterns()
        self.prostitution_patterns = self._load_prostitution_patterns()
        self.spam_patterns = self._load_spam_patterns()
        self.suspicious_patterns = self._load_suspicious_patterns()
    
    def _load_drug_patterns(self) -> List[str]:
        """Загружает паттерны для наркотиков"""
        return [
            # Наркотики
            r'\b(наркотик|нарко|нарк|доза|дозы|дозировка)\b',
            r'\b(кокаин|кокс|кок|кока)\b',
            r'\b(героин|гер|герыч)\b',
            r'\b(амфетамин|амф|спид|скорость)\b',
            r'\b(марихуана|травка|конопля|гашиш|план)\b',
            r'\b(лсд|lsd|кислота)\b',
            r'\b(экстази|мдма|молли)\b',
            r'\b(мефедрон|меф|соль)\b',
            r'\b(спайс|микс|курительные)\b',
            r'\b(таблетки|таблы|пилюли)\b',
            
            # Сленг и коды
            r'\b(белый|порошок|порош)\b',
            r'\b(кристалл|кристаллы)\b',
            r'\b(шишки|шиш)\b',
            r'\b(грибы|гриб|грибочки)\b',
            r'\b(травка|траву|травы)\b',
            
            # Действия
            r'\b(продам|продаю|продажа)\b.*\b(нарко|доза|вещество)\b',
            r'\b(купить|куплю|покупка)\b.*\b(нарко|доза|вещество)\b',
            r'\b(доставка|доставлю)\b.*\b(нарко|доза|вещество)\b',
            r'\b(закладка|закладки)\b',
            r'\b(торг|торговля)\b.*\b(нарко|доза|вещество)\b',
        ]
    
    def _load_prostitution_patterns(self) -> List[str]:
        """Загружает паттерны для проституции"""
        return [
            # Прямые упоминания
            r'\b(проститутк|проституция|эскорт|эскортница)\b',
            r'\b(интим|интимные|интимка)\b',
            r'\b(секс|сексуальные|секс-услуги)\b',
            r'\b(массаж|массажистка)\b.*\b(интим|секс|эрот)\b',
            
            # Сленг и коды
            r'\b(девочки|девушки|женщины)\b.*\b(для|на|услуги)\b',
            r'\b(встречи|встреча)\b.*\b(интим|секс|эрот)\b',
            r'\b(сопровождение|сопровождаю)\b',
            r'\b(досуг|досуговая)\b',
            r'\b(релакс|релаксация)\b',
            
            # Цены и услуги
            r'\b(час|часа|часов)\b.*\b(руб|₽|долл|\$|евро|€)\b',
            r'\b(ночь|ночи|ночей)\b.*\b(руб|₽|долл|\$|евро|€)\b',
            r'\b(выезд|выезжаю|выездная)\b',
            r'\b(отель|номер|квартира)\b.*\b(встреча|услуги)\b',
            
            # Контакты и реклама
            r'\b(звоните|пишите|телефон|телеграм)\b.*\b(девушк|женщин|услуги)\b',
            r'\b(фото|фотографии|портфолио)\b.*\b(девушк|женщин|услуги)\b',
        ]
    
    def _load_spam_patterns(self) -> List[str]:
        """Загружает паттерны для спама"""
        return [
            # Финансовые пирамиды
            r'\b(заработок|заработать|доход)\b.*\b(без|легко|быстро)\b',
            r'\b(инвестиции|инвестируй|вложи)\b.*\b(прибыль|доход|процент)\b',
            r'\b(криптовалют|биткоин|эфир)\b.*\b(заработок|доход|прибыль)\b',
            r'\b(пирамида|млм|сетевой)\b',
            
            # Мошенничество
            r'\b(выигрыш|выиграл|приз)\b.*\b(деньги|руб|₽|долл|\$)\b',
            r'\b(бесплатно|даром|подарок)\b.*\b(деньги|руб|₽|долл|\$)\b',
            r'\b(срочно|быстро|сегодня)\b.*\b(деньги|руб|₽|долл|\$)\b',
            
            # Спам-ссылки
            r'\b(переходи|перейди|ссылка)\b.*\b(здесь|тут|ниже)\b',
            r'\b(канал|группа|чат)\b.*\b(подписывайся|подпишись)\b',
            r'\b(реклама|рекламирую|продвигаю)\b',
        ]
    
    def _load_suspicious_patterns(self) -> List[str]:
        """Загружает общие подозрительные паттерны"""
        return [
            # Подозрительные символы
            r'[🔞💊💉💰💸💵💴💶💷💳💎💍💋💄👄👅👃👂👁👀👤👥👦👧👨👩👴👵👶👷👮👳👲👱👰👸🤴🤵🤰🤱🤲🤳🤴🤵🤰🤱🤲🤳]',
            
            # Множественные символы
            r'(.)\1{4,}',  # 5+ одинаковых символов подряд
            
            # Подозрительные комбинации
            r'\b(тест|test|demo|sample)\b',
            r'\b(бот|bot|admin|админ)\b',
            r'\b(продам|продаю|куплю|куплю)\b.*\b(все|всё|что|что-то)\b',
        ]
    
    def analyze_bio_content(self, bio_text: str) -> Dict[str, any]:
        """
        Анализирует содержимое био на подозрительный контент
        
        Args:
            bio_text: Текст био пользователя
            
        Returns:
            Словарь с результатами анализа
        """
        if not bio_text or not bio_text.strip():
            return {
                "is_suspicious": False,
                "risk_score": 0,
                "categories": [],
                "matched_patterns": [],
                "reason": "Био отсутствует"
            }
        
        bio_lower = bio_text.lower().strip()
        risk_score = 0
        categories = []
        matched_patterns = []
        
        # Проверяем наркотики
        drug_matches = self._check_patterns(bio_lower, self.drug_patterns, "наркотики")
        if drug_matches:
            risk_score += 50
            categories.append("наркотики")
            matched_patterns.extend(drug_matches)
        
        # Проверяем проституцию
        prostitution_matches = self._check_patterns(bio_lower, self.prostitution_patterns, "проституция")
        if prostitution_matches:
            risk_score += 40
            categories.append("проституция")
            matched_patterns.extend(prostitution_matches)
        
        # Проверяем спам
        spam_matches = self._check_patterns(bio_lower, self.spam_patterns, "спам")
        if spam_matches:
            risk_score += 30
            categories.append("спам")
            matched_patterns.extend(spam_matches)
        
        # Проверяем общие подозрительные паттерны
        suspicious_matches = self._check_patterns(bio_lower, self.suspicious_patterns, "подозрительное")
        if suspicious_matches:
            risk_score += 20
            categories.append("подозрительное")
            matched_patterns.extend(suspicious_matches)
        
        # Дополнительные проверки
        if len(bio_text) > 200:
            risk_score += 10
            categories.append("слишком длинное био")
        
        if bio_text.count('\n') > 5:
            risk_score += 10
            categories.append("много переносов строк")
        
        # Ограничиваем максимальный балл
        risk_score = min(risk_score, 100)
        
        return {
            "is_suspicious": risk_score >= 30,
            "risk_score": risk_score,
            "categories": categories,
            "matched_patterns": matched_patterns,
            "reason": f"Обнаружены: {', '.join(categories)}" if categories else "Био в порядке"
        }
    
    def _check_patterns(self, text: str, patterns: List[str], category: str) -> List[str]:
        """
        Проверяет текст на соответствие паттернам
        
        Args:
            text: Текст для проверки
            patterns: Список регулярных выражений
            category: Категория паттернов
            
        Returns:
            Список найденных совпадений
        """
        matches = []
        for pattern in patterns:
            try:
                if re.search(pattern, text, re.IGNORECASE):
                    matches.append(f"{category}: {pattern}")
            except re.error as e:
                logger.warning(f"Ошибка в регулярном выражении {pattern}: {e}")
        
        return matches

# Глобальный экземпляр для использования в других модулях
bio_analyzer = BioContentAnalyzer()
