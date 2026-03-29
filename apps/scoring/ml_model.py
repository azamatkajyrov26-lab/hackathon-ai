"""
AI/ML модель скоринга сельхозпроизводителей.

Использует Gradient Boosting для предсказания оценки заявителя
на основе данных из 7 внешних информационных систем.

Модель обеспечивает:
  - Предсказание итогового балла (регрессия)
  - Классификацию рекомендации (approve/review/reject)
  - Explainability через feature importances
  - SHAP-подобный анализ вклада каждого фактора
"""
import logging
import os
import pickle
from pathlib import Path

import numpy as np
from sklearn.ensemble import GradientBoostingRegressor, GradientBoostingClassifier
from sklearn.model_selection import cross_val_score, StratifiedKFold
from sklearn.preprocessing import LabelEncoder

logger = logging.getLogger(__name__)

MODEL_DIR = Path(__file__).resolve().parent / 'ml_models'
SCORE_MODEL_PATH = MODEL_DIR / 'score_model.pkl'
REC_MODEL_PATH = MODEL_DIR / 'recommendation_model.pkl'
META_PATH = MODEL_DIR / 'model_meta.pkl'

# 20 признаков, извлекаемых из данных 7 внешних систем
FEATURE_NAMES = [
    'giss_registered',                 # ГИСС: зарегистрирован
    'growth_rate',                     # ГИСС: темп роста валовой продукции (%)
    'gross_production_prev',           # ГИСС: валовая продукция пред. год
    'gross_production_before',         # ГИСС: валовая продукция год ранее
    'obligations_met',                 # ГИСС: встречные обязательства выполнены
    'total_subsidies_received',        # ГИСС: всего получено субсидий (тг)
    'ias_registered',                  # ИАС РСЖ: зарегистрирован
    'subsidy_history_count',           # ИАС РСЖ: кол-во субсидий в истории
    'subsidy_success_rate',            # ИАС РСЖ: доля успешных субсидий
    'pending_returns',                 # ИАС РСЖ: невозвращённые субсидии
    'total_verified_animals',          # ИС ИСЖ: верифицированных животных
    'total_rejected_animals',          # ИС ИСЖ: отклонённых животных
    'animal_age_valid_ratio',          # ИС ИСЖ: доля животных с допустимым возрастом
    'esf_total_amount',                # ИС ЭСФ: общая сумма ЭСФ
    'esf_invoice_count',               # ИС ЭСФ: количество ЭСФ
    'esf_confirmed_ratio',             # ИС ЭСФ: доля подтверждённых ЭСФ
    'has_agricultural_land',           # ЕГКН: есть с/х земля
    'total_agricultural_area',         # ЕГКН: общая площадь с/х земли (га)
    'entity_type_encoded',             # Тип заявителя (0=физлицо, 1=юрлицо, 2=СПК)
    'treasury_payment_count',          # Казначейство: кол-во успешных платежей
]

FEATURE_NAMES_RU = {
    'giss_registered': 'Регистрация в ГИСС',
    'growth_rate': 'Темп роста продукции',
    'gross_production_prev': 'Валовая продукция (пред. год)',
    'gross_production_before': 'Валовая продукция (год ранее)',
    'obligations_met': 'Выполнение обязательств',
    'total_subsidies_received': 'Общая сумма субсидий',
    'ias_registered': 'Регистрация в ИАС РСЖ',
    'subsidy_history_count': 'Количество субсидий',
    'subsidy_success_rate': 'Успешность субсидий',
    'pending_returns': 'Невозвращённые субсидии',
    'total_verified_animals': 'Верифицированные животные',
    'total_rejected_animals': 'Отклонённые животные',
    'animal_age_valid_ratio': 'Допустимый возраст животных',
    'esf_total_amount': 'Сумма ЭСФ',
    'esf_invoice_count': 'Количество ЭСФ',
    'esf_confirmed_ratio': 'Подтверждённые ЭСФ',
    'has_agricultural_land': 'Наличие с/х земли',
    'total_agricultural_area': 'Площадь с/х земли',
    'entity_type_encoded': 'Тип заявителя',
    'treasury_payment_count': 'Платежи Казначейства',
}

ENTITY_TYPE_MAP = {'individual': 0, 'legal': 1, 'cooperative': 2}


def extract_features(entity_data: dict) -> np.ndarray:
    """
    Извлекает 20 числовых признаков из данных EmulatedEntity.

    Args:
        entity_data: словарь с ключами giss_data, ias_rszh_data,
                     easu_data, is_iszh_data, is_esf_data, egkn_data,
                     treasury_data, entity_type

    Returns:
        numpy array shape (20,)
    """
    giss = entity_data.get('giss_data') or {}
    ias = entity_data.get('ias_rszh_data') or {}
    is_iszh = entity_data.get('is_iszh_data') or {}
    is_esf = entity_data.get('is_esf_data') or {}
    egkn = entity_data.get('egkn_data') or {}
    treasury = entity_data.get('treasury_data') or {}
    entity_type = entity_data.get('entity_type', 'individual')

    # Subsidy history stats
    subsidy_history = ias.get('subsidy_history', [])
    total_subs = len(subsidy_history)
    successful = sum(
        1 for h in subsidy_history
        if h.get('status') == 'executed' and h.get('obligations_met', False)
    )
    success_rate = successful / total_subs if total_subs > 0 else 0.5

    # Animal stats
    animals = is_iszh.get('animals', [])
    total_animals = len(animals)
    age_valid_count = sum(1 for a in animals if a.get('age_valid', False))
    age_valid_ratio = age_valid_count / total_animals if total_animals > 0 else 0.5

    # ESF stats
    invoices = is_esf.get('invoices', [])
    confirmed_count = sum(1 for inv in invoices if inv.get('payment_confirmed', False))
    esf_confirmed_ratio = confirmed_count / len(invoices) if invoices else 0

    # Treasury
    payments = treasury.get('payments', [])

    features = np.array([
        float(giss.get('registered', False)),
        float(giss.get('growth_rate', 0)),
        float(giss.get('gross_production_previous_year', 0)) / 1_000_000,  # в млн тг
        float(giss.get('gross_production_year_before', 0)) / 1_000_000,
        float(giss.get('obligations_met', True)),
        float(giss.get('total_subsidies_received', 0)) / 1_000_000,
        float(ias.get('registered', False)),
        float(total_subs),
        float(success_rate),
        float(ias.get('pending_returns', 0)),
        float(is_iszh.get('total_verified', 0)),
        float(is_iszh.get('total_rejected', 0)),
        float(age_valid_ratio),
        float(is_esf.get('total_amount', 0)) / 1_000_000,
        float(is_esf.get('invoice_count', 0)),
        float(esf_confirmed_ratio),
        float(egkn.get('has_agricultural_land', False)),
        float(egkn.get('total_agricultural_area', 0)),
        float(ENTITY_TYPE_MAP.get(entity_type, 0)),
        float(len(payments)),
    ], dtype=np.float64)

    return features


def train_model(entities_data: list[dict], scores: list[float], recommendations: list[str]):
    """
    Обучает ML модели на данных из EmulatedEntity.

    Args:
        entities_data: список словарей с данными сущностей
        scores: список итоговых баллов (0-100)
        recommendations: список рекомендаций ('approve', 'review', 'reject')

    Returns:
        dict с метриками обучения
    """
    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    # Извлекаем признаки
    X = np.array([extract_features(ed) for ed in entities_data])
    y_score = np.array(scores, dtype=np.float64)

    # Кодируем рекомендации
    le = LabelEncoder()
    y_rec = le.fit_transform(recommendations)

    logger.info('Обучение модели: %d примеров, %d признаков', X.shape[0], X.shape[1])

    # --- Модель регрессии (предсказание балла) ---
    score_model = GradientBoostingRegressor(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.1,
        min_samples_split=10,
        min_samples_leaf=5,
        subsample=0.8,
        random_state=42,
    )
    n_cv_folds = min(5, len(set(recommendations)))  # не больше кол-ва классов
    n_cv_folds = max(2, n_cv_folds)
    score_cv = cross_val_score(score_model, X, y_score, cv=n_cv_folds, scoring='r2')
    score_model.fit(X, y_score)

    # --- Модель классификации (рекомендация) ---
    rec_model = GradientBoostingClassifier(
        n_estimators=150,
        max_depth=3,
        learning_rate=0.1,
        min_samples_split=10,
        min_samples_leaf=5,
        subsample=0.8,
        random_state=42,
    )
    # Стратифицированная кросс-валидация для баланса классов
    unique_classes = len(set(recommendations))
    if unique_classes >= 2:
        min_class_count = min(np.bincount(y_rec))
        cv_folds = min(5, min_class_count)
        cv_folds = max(2, cv_folds)
        skf = StratifiedKFold(n_splits=cv_folds, shuffle=True, random_state=42)
        rec_cv = cross_val_score(rec_model, X, y_rec, cv=skf, scoring='accuracy')
    else:
        rec_cv = np.array([1.0])
    rec_model.fit(X, y_rec)

    # Сохраняем модели
    with open(SCORE_MODEL_PATH, 'wb') as f:
        pickle.dump(score_model, f)
    with open(REC_MODEL_PATH, 'wb') as f:
        pickle.dump(rec_model, f)

    meta = {
        'feature_names': FEATURE_NAMES,
        'label_encoder_classes': le.classes_.tolist(),
        'score_r2_cv': score_cv.tolist(),
        'rec_accuracy_cv': rec_cv.tolist(),
        'n_samples': len(scores),
        'score_feature_importances': score_model.feature_importances_.tolist(),
        'rec_feature_importances': rec_model.feature_importances_.tolist(),
    }
    with open(META_PATH, 'wb') as f:
        pickle.dump(meta, f)

    metrics = {
        'n_samples': len(scores),
        'score_r2_mean': float(np.mean(score_cv)),
        'score_r2_std': float(np.std(score_cv)),
        'rec_accuracy_mean': float(np.mean(rec_cv)),
        'rec_accuracy_std': float(np.std(rec_cv)),
        'top_features_score': _get_top_features(score_model.feature_importances_),
        'top_features_rec': _get_top_features(rec_model.feature_importances_),
    }

    logger.info(
        'Модель обучена: R²=%.3f±%.3f, Accuracy=%.3f±%.3f',
        metrics['score_r2_mean'], metrics['score_r2_std'],
        metrics['rec_accuracy_mean'], metrics['rec_accuracy_std'],
    )

    return metrics


def _get_top_features(importances, top_n=5):
    """Возвращает топ-N важных признаков."""
    indices = np.argsort(importances)[::-1][:top_n]
    return [
        {
            'feature': FEATURE_NAMES[i],
            'feature_ru': FEATURE_NAMES_RU.get(FEATURE_NAMES[i], FEATURE_NAMES[i]),
            'importance': float(importances[i]),
        }
        for i in indices
    ]


# --- Кэш загруженных моделей ---
_score_model = None
_rec_model = None
_meta = None


def _load_models():
    """Загружает модели из файлов (с кэшированием)."""
    global _score_model, _rec_model, _meta

    if _score_model is not None:
        return True

    if not SCORE_MODEL_PATH.exists() or not REC_MODEL_PATH.exists():
        logger.warning('ML модели не найдены. Запустите: python manage.py train_model')
        return False

    try:
        with open(SCORE_MODEL_PATH, 'rb') as f:
            _score_model = pickle.load(f)
        with open(REC_MODEL_PATH, 'rb') as f:
            _rec_model = pickle.load(f)
        with open(META_PATH, 'rb') as f:
            _meta = pickle.load(f)
        logger.info('ML модели загружены успешно')
        return True
    except Exception as e:
        logger.error('Ошибка загрузки ML моделей: %s', e)
        return False


def predict_score(entity_data: dict) -> dict | None:
    """
    Предсказывает балл и рекомендацию с помощью ML модели.

    Args:
        entity_data: данные из EmulatedEntity

    Returns:
        dict с предсказанием и explainability, или None если модель недоступна
    """
    if not _load_models():
        return None

    features = extract_features(entity_data)
    X = features.reshape(1, -1)

    # Предсказание
    ml_score = float(_score_model.predict(X)[0])
    ml_score = max(0.0, min(100.0, ml_score))

    rec_proba = _rec_model.predict_proba(X)[0]
    rec_classes = _meta['label_encoder_classes']
    rec_idx = int(np.argmax(rec_proba))
    ml_recommendation = rec_classes[rec_idx]

    # Уверенность модели
    confidence = float(rec_proba[rec_idx])

    # Explainability: вклад каждого признака
    feature_contributions = _compute_feature_contributions(features)

    return {
        'ml_score': round(ml_score, 2),
        'ml_recommendation': ml_recommendation,
        'confidence': round(confidence, 3),
        'recommendation_probabilities': {
            rec_classes[i]: round(float(rec_proba[i]), 3)
            for i in range(len(rec_classes))
        },
        'feature_contributions': feature_contributions,
        'model_version': '2.0-ml',
    }


def _compute_feature_contributions(features: np.ndarray) -> list[dict]:
    """
    Вычисляет вклад каждого признака в предсказание.
    Использует feature importances × feature value (нормализованный).
    """
    importances = np.array(_meta['score_feature_importances'])

    # Нормализуем значения признаков для сравнения
    # Используем простую нормализацию: feature * importance
    contributions = importances * np.abs(features)
    total = np.sum(contributions) if np.sum(contributions) > 0 else 1

    result = []
    sorted_indices = np.argsort(contributions)[::-1]

    for i in sorted_indices:
        if contributions[i] < 0.001:
            continue
        result.append({
            'feature': FEATURE_NAMES[i],
            'feature_ru': FEATURE_NAMES_RU.get(FEATURE_NAMES[i], FEATURE_NAMES[i]),
            'value': float(features[i]),
            'importance': float(importances[i]),
            'contribution': float(contributions[i]),
            'contribution_pct': round(float(contributions[i] / total * 100), 1),
            'direction': 'positive' if features[i] > 0 else 'neutral',
        })

    return result[:10]  # Топ-10 факторов


def get_model_info() -> dict | None:
    """Возвращает метаданные обученной модели."""
    if not _load_models():
        return None

    return {
        'n_samples': _meta.get('n_samples', 0),
        'score_r2': round(float(np.mean(_meta.get('score_r2_cv', [0]))), 3),
        'rec_accuracy': round(float(np.mean(_meta.get('rec_accuracy_cv', [0]))), 3),
        'feature_names': FEATURE_NAMES,
        'feature_names_ru': FEATURE_NAMES_RU,
        'top_features_score': _get_top_features(
            np.array(_meta['score_feature_importances'])
        ),
        'top_features_rec': _get_top_features(
            np.array(_meta['rec_feature_importances'])
        ),
    }
