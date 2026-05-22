from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from enum import Enum

class ShiftType(str, Enum):
    DAY       = '주'
    NIGHT     = '야'
    OFF       = '비'
    HOLIDAY   = '휴'
    ANNUAL    = '연'
    SPECIAL   = '특'
    EDUCATION = '교'

    def is_off_day(self) -> bool:
        """실제 휴가/휴무로 집계되는 유형"""
        return self in (ShiftType.HOLIDAY, ShiftType.ANNUAL, ShiftType.SPECIAL)

    def is_work_day(self) -> bool:
        """근무일로 집계되는 유형 (비번·교육 포함)"""
        return self in (ShiftType.DAY, ShiftType.NIGHT, ShiftType.OFF, ShiftType.EDUCATION)


ALL_SHIFTS: List[ShiftType] = list(ShiftType)

@dataclass
class FixedSchedule:
    day: int
    shift: ShiftType

@dataclass
class Employee:
    name: str
    prefer_day:      bool = False
    prefer_night:    bool = False
    fixed_schedules: List[FixedSchedule] = field(default_factory=list)

    def get_fixed_shift(self, day: int) -> Optional[ShiftType]:
        for fs in self.fixed_schedules:
            if fs.day == day:
                return fs.shift
        return None

@dataclass
class MonthSchedule:
    year:           int
    month:          int
    num_days:       int
    employees:      List[Employee]
    schedule:       Dict[str, Dict[int, ShiftType]] = field(default_factory=dict)
    score:          int = 0
    solution_label: str = "A"

    def get_shift(self, emp_name: str, day: int) -> Optional[ShiftType]:
        return self.schedule.get(emp_name, {}).get(day)

    def get_stats(self, emp_name: str) -> Dict:
        shifts = self.schedule.get(emp_name, {})
        cnt = {s: 0 for s in ShiftType}
        for s in shifts.values():
            cnt[s] += 1
        holiday_total = (cnt[ShiftType.HOLIDAY]
                         + cnt[ShiftType.ANNUAL]
                         + cnt[ShiftType.SPECIAL])
        return {
            # 💡 주간 횟수에 교육 횟수를 더해서 표기합니다.
            '주간': cnt[ShiftType.DAY] + cnt[ShiftType.EDUCATION],
            '야간': cnt[ShiftType.NIGHT],
            '비번': cnt[ShiftType.OFF],
            '휴일': cnt[ShiftType.HOLIDAY],
            '연가': cnt[ShiftType.ANNUAL],
            '특별': cnt[ShiftType.SPECIAL],
            '교육': cnt[ShiftType.EDUCATION],
            '총휴일': holiday_total,
            '근무일': self.num_days - holiday_total,
        }
