"""
Модуль для оценки возраста аккаунта Telegram по user_id
Использует линейную интерполяцию на основе известных точек соответствия ID -> дата создания
"""

from bisect import bisect_left
from datetime import datetime, timezone, timedelta
import json
import logging
from typing import List, Tuple, Optional
import os

logger = logging.getLogger(__name__)

class AccountAgeEstimator:
    """Класс для оценки возраста аккаунта по user_id"""
    
    def __init__(self, mapping_file: str = "bot/services/telegram_id_mapping.json"):
        """
        Инициализация с файлом маппинга
        
        Args:
            mapping_file: Путь к JSON файлу с эталонными точками [user_id, unix_timestamp]
        """
        self.mapping_file = mapping_file
        self.mapping: List[Tuple[int, int]] = []
        self.load_mapping()
    
    def load_mapping(self) -> None:
        """Загружает маппинг из JSON файла"""
        try:
            if not os.path.exists(self.mapping_file):
                logger.warning(f"Файл маппинга {self.mapping_file} не найден. Создаю базовый маппинг.")
                self.create_default_mapping()
                return
            
            with open(self.mapping_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Убеждаемся, что данные отсортированы по user_id по возрастанию
            self.mapping = sorted([(int(x[0]), int(x[1])) for x in data], key=lambda x: x[0])
            logger.info(f"Загружен маппинг с {len(self.mapping)} точками")
            
        except Exception as e:
            logger.error(f"Ошибка загрузки маппинга: {e}")
            self.create_default_mapping()
    
    def create_default_mapping(self) -> None:
        """Создает базовый маппинг на основе известных данных"""
        # Базовые точки на основе известных данных Telegram
        default_mapping = [
            [1000000, 1388534400],    # ~2014
            [200000000, 1451606400],  # ~2016  
            [500000000, 1504224000],  # ~2017
            [1000000000, 1609459200], # ~2021
            [2000000000, 1640995200], # ~2022
            [4000000000, 1704067200], # ~2024
            [6000000000, 1735689600], # ~2025
            [8000000000, 1767225600], # ~2026 (прогноз)
        ]
        
        self.mapping = [(int(x[0]), int(x[1])) for x in default_mapping]
        
        # Сохраняем базовый маппинг
        try:
            os.makedirs(os.path.dirname(self.mapping_file), exist_ok=True)
            with open(self.mapping_file, 'w', encoding='utf-8') as f:
                json.dump(default_mapping, f, indent=2)
            logger.info(f"Создан базовый маппинг в {self.mapping_file}")
        except Exception as e:
            logger.error(f"Ошибка сохранения базового маппинга: {e}")
    
    def estimate_creation_timestamp(self, user_id: int) -> int:
        """
        Оценка времени создания (unix timestamp) по user_id методом линейной интерполяции
        
        Args:
            user_id: ID пользователя Telegram
            
        Returns:
            Unix timestamp предполагаемой даты создания
        """
        if not self.mapping:
            raise ValueError("Маппинг пуст")
        
        ids = [p[0] for p in self.mapping]
        pos = bisect_left(ids, user_id)
        
        # Если user_id <= минимальный образец — вернуть минимальный timestamp
        if pos == 0:
            return self.mapping[0][1]
        
        # Если больше чем все образцы — вернуть последний timestamp
        if pos >= len(self.mapping):
            return self.mapping[-1][1]
        
        id_lo, ts_lo = self.mapping[pos-1]
        id_hi, ts_hi = self.mapping[pos]
        
        # Если попали точно в образец
        if user_id == id_lo:
            return ts_lo
        if user_id == id_hi:
            return ts_hi
        
        # Линейная интерполяция
        frac = (user_id - id_lo) / (id_hi - id_lo)
        est_ts = int(ts_lo + frac * (ts_hi - ts_lo))
        return est_ts
    
    def estimate_creation_datetime(self, user_id: int) -> datetime:
        """
        Оценка даты создания аккаунта
        
        Args:
            user_id: ID пользователя Telegram
            
        Returns:
            datetime объект предполагаемой даты создания
        """
        ts = self.estimate_creation_timestamp(user_id)
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    
    def get_account_age_days(self, user_id: int) -> int:
        """
        Получает возраст аккаунта в днях
        
        Args:
            user_id: ID пользователя Telegram
            
        Returns:
            Возраст аккаунта в днях
        """
        creation_date = self.estimate_creation_datetime(user_id)
        now = datetime.now(timezone.utc)
        age_delta = now - creation_date
        return age_delta.days
    
    def calculate_age_risk_score(self, user_id: int) -> Tuple[int, str, str]:
        """
        Вычисляет риск на основе возраста аккаунта
        
        Args:
            user_id: ID пользователя Telegram
            
        Returns:
            Tuple[score, label, description]
            - score: 0-100 (балл риска)
            - label: короткий идентификатор
            - description: описание категории
        """
        age_days = self.get_account_age_days(user_id)
        creation_date = self.estimate_creation_datetime(user_id)
        
        if age_days < 1:
            return 90, "very_new", f"Очень новый аккаунт ({age_days} дней)"
        elif age_days < 7:
            return 80, "new", f"Новый аккаунт ({age_days} дней)"
        elif age_days < 30:
            return 60, "young", f"Молодой аккаунт ({age_days} дней)"
        elif age_days < 180:
            return 30, "mature", f"Зрелый аккаунт ({age_days} дней)"
        else:
            return 0, "old", f"Старый аккаунт ({age_days} дней)"
    
    def get_detailed_age_info(self, user_id: int) -> dict:
        """
        Получает детальную информацию о возрасте аккаунта
        
        Args:
            user_id: ID пользователя Telegram
            
        Returns:
            Словарь с детальной информацией
        """
        creation_date = self.estimate_creation_datetime(user_id)
        age_days = self.get_account_age_days(user_id)
        score, label, description = self.calculate_age_risk_score(user_id)
        
        return {
            "user_id": user_id,
            "estimated_creation_date": creation_date,
            "age_days": age_days,
            "risk_score": score,
            "risk_label": label,
            "risk_description": description,
            "creation_date_str": creation_date.strftime('%Y-%m-%d %H:%M:%S UTC'),
            "age_str": f"{age_days} дней"
        }

# Глобальный экземпляр для использования в других модулях
account_age_estimator = AccountAgeEstimator()
