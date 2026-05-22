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
        return self in (ShiftType.HOLIDAY, ShiftType.ANNUAL, ShiftType.SPECIAL)

    def is_work_day(self) -> bool:
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
    desired_schedules: List[FixedSchedule] = field(default_factory=list) 

    def get_fixed_shift(self, day: int) -> Optional[ShiftType]:
        for fs in self.fixed_schedules:
            if fs.day == day:
                return fs.shift
        return None

    def get_desired_shift(self, day: int) -> Optional[ShiftType]:
        for ds in self.desired_schedules:
            if ds.day == day:
                return ds.shift
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
            # 💡 교육을 주간에서 완전히 분리 (기존 로직으로 원복)
            '주간': cnt[ShiftType.DAY], 
            '야간': cnt[ShiftType.NIGHT],
            '비번': cnt[ShiftType.OFF],
            '휴일': cnt[ShiftType.HOLIDAY],
            '연가': cnt[ShiftType.ANNUAL],
            '특별': cnt[ShiftType.SPECIAL],
            '교육': cnt[ShiftType.EDUCATION],
            '총휴일': holiday_total,
            '근무일': self.num_days - holiday_total,
        }
