
import calendar
from datetime import date
from typing import Dict, List

try:
    import holidays as hol_lib
    _HAS_HOLIDAYS = True
except ImportError:
    _HAS_HOLIDAYS = False


def get_month_info(year: int, month: int) -> Dict:
    """
    월별 달력 정보 계산
    Returns:
        num_days        : 해당 월 총 일수
        weekends        : 토·일 날짜 목록
        public_holidays : 법정 공휴일 날짜 목록 (평일 기준)
        base_off_days   : 기본 휴일 수 (주말 + 공휴일 합계)
    """
    num_days = calendar.monthrange(year, month)[1]
    weekends, pub_hols = [], []
    kr_holidays = hol_lib.KR(years=year) if _HAS_HOLIDAYS else {}

    for day in range(1, num_days + 1):
        d = date(year, month, day)
        if d.weekday() >= 5:
            weekends.append(day)
        elif _HAS_HOLIDAYS and d in kr_holidays:
            pub_hols.append(day)

    return {
        'num_days':        num_days,
        'weekends':        weekends,
        'public_holidays': pub_hols,
        'base_off_days':   len(weekends) + len(pub_hols),
    }


def month_label(year: int, month: int) -> str:
    return f"{year}-{month:02d}"
