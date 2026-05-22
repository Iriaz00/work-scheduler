from __future__ import annotations
from typing import Dict, List, Optional, Tuple
import calendar as cal_module
import datetime

from ortools.sat.python import cp_model
from models import ALL_SHIFTS, Employee, FixedSchedule, MonthSchedule, ShiftType

class ShiftScheduler:
    _STATUS = {
        cp_model.OPTIMAL:    "✅ 최적해",
        cp_model.FEASIBLE:   "⚠️  가능해(비최적)",
        cp_model.INFEASIBLE: "❌ 불가능(제약 충돌)",
        cp_model.UNKNOWN:    "⏱️  탐색 실패(시간 초과)",
    }

    def __init__(
        self,
        year: int,
        month: int,
        employees: List[Employee],
        carryover: Optional[Dict[str, Dict[int, ShiftType]]] = None,
        num_solutions: int = 3,
        time_limit: float = 60.0,
    ):
        self.year          = year
        self.month         = month
        self.employees     = [
            Employee(e.name, e.prefer_day, e.prefer_night, list(e.fixed_schedules))
            for e in employees
        ]
        self.carryover      = carryover or {}
        self.num_solutions = num_solutions
        self.time_limit    = time_limit

        self.num_days = cal_module.monthrange(year, month)[1]
        self.days     = list(range(1, self.num_days + 1))
        self.n_emp    = len(self.employees)

        self._preprocess_carryover()

    def _carry(self, emp_name: str, day: int) -> Optional[ShiftType]:
        return self.carryover.get(emp_name, {}).get(day)

    def _carry_consec_days(self, emp_name: str) -> int:
        """💡 전월 말미 연속 근무 체크 시 '교육'도 '주간' 피로도로 합산합니다."""
        cnt = 0
        for d in (0, -1, -2, -3):
            if self._carry(emp_name, d) in (ShiftType.DAY, ShiftType.EDUCATION):
                cnt += 1
            else:
                break
        return cnt

    def _preprocess_carryover(self):
        for emp in self.employees:
            existing = {fs.day for fs in emp.fixed_schedules}
            c0  = self._carry(emp.name,  0)
            cm1 = self._carry(emp.name, -1)

            def fix(day: int, shift: ShiftType):
                if day <= self.num_days and day not in existing:
                    emp.fixed_schedules.append(FixedSchedule(day, shift))
                    existing.add(day)

            if c0 == ShiftType.NIGHT:
                fix(1, ShiftType.OFF)
                fix(2, ShiftType.HOLIDAY)
            elif cm1 == ShiftType.NIGHT:
                fix(1, ShiftType.HOLIDAY)

    def solve(self) -> List[MonthSchedule]:
        results: List[MonthSchedule] = []
        labels = ['A', 'B', 'C', 'D', 'E']

        for i in range(self.num_solutions):
            lbl = labels[i]
            print(f"[{lbl}안] 탐색 중 ... ", end="", flush=True)
            result = self._solve_once(results, lbl)
            if result is None:
                print()
                break
            results.append(result)
            print(f" 점수: {result.score}")

        return results

    def _solve_once(
        self,
        prev_results: List[MonthSchedule],
        label: str,
    ) -> Optional[MonthSchedule]:

        model = cp_model.CpModel()
        sv    = self._create_vars(model)

        self._c1_one_shift_per_day(model, sv)
        self._c2_night_sequence(model, sv)
        self._c3_c4_consecutive_limits(model, sv)
        self._c5_daily_staffing(model, sv)
        self._c6_equal_holidays(model, sv)

        for p in prev_results:
            self._exclude(model, sv, p)

        obj_terms = self._objective(model, sv)
        model.Maximize(cp_model.LinearExpr.Sum(obj_terms))

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = self.time_limit
        solver.parameters.log_search_progress = False

        status     = solver.Solve(model)
        status_str = self._STATUS.get(status, f"코드:{status}")
        print(status_str, end="  ")

        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return None

        schedule: Dict[str, Dict[int, ShiftType]] = {}
        for e, emp in enumerate(self.employees):
            schedule[emp.name] = {}
            for d in self.days:
                for s in ALL_SHIFTS:
                    if solver.Value(sv[(e, d, s)]) == 1:
                        schedule[emp.name][d] = s
                        break

        return MonthSchedule(
            year=self.year, month=self.month, num_days=self.num_days,
            employees=self.employees, schedule=schedule,
            score=int(solver.ObjectiveValue()), solution_label=label,
        )

    def _create_vars(self, model: cp_model.CpModel) -> Dict:
        sv: Dict[Tuple, cp_model.IntVar] = {}
        RESTRICTED_SHIFTS = [ShiftType.ANNUAL, ShiftType.SPECIAL, ShiftType.EDUCATION]
        
        for e, emp in enumerate(self.employees):
            for d in self.days:
                fixed = emp.get_fixed_shift(d)
                for s in ALL_SHIFTS:
                    var = model.NewBoolVar(f"e{e}_d{d}_{s.value}")
                    if fixed is not None:
                        model.Add(var == (1 if s == fixed else 0))
                    else:
                        if s in RESTRICTED_SHIFTS:
                            model.Add(var == 0)
                    sv[(e, d, s)] = var
        return sv

    def _c1_one_shift_per_day(self, model, sv):
        for e in range(self.n_emp):
            for d in self.days:
                model.AddExactlyOne([sv[(e, d, s)] for s in ALL_SHIFTS])

    def _c2_night_sequence(self, model, sv):
        D = ShiftType
        for e, emp in enumerate(self.employees):
            carry = self.carryover.get(emp.name, {})

            for d in self.days:
                night = sv[(e, d, D.NIGHT)]
                off_d = sv[(e, d, D.OFF)]

                if d + 1 in self.days:
                    model.AddImplication(night, sv[(e, d + 1, D.OFF)])
                if d + 2 in self.days:
                    model.AddImplication(night, sv[(e, d + 2, D.HOLIDAY)])

                if d - 1 in self.days:
                    model.AddImplication(off_d, sv[(e, d - 1, D.NIGHT)])
                else:
                    if carry.get(0) != D.NIGHT:
                        model.Add(off_d == 0)

    def _c3_c4_consecutive_limits(self, model, sv):
        """💡 '교육'을 '주간 근무'와 동일하게 피로도로 합산하여 연속근무 제한(C3, C4) 적용"""
        D = ShiftType
        for e, emp in enumerate(self.employees):
            k = self._carry_consec_days(emp.name)

            for d in range(1, self.num_days + 1):
                if d + 4 <= self.num_days:
                    # DAY와 EDUCATION을 더해서 주간 출근 횟수로 계산
                    day_window = [(sv[(e, d + i, D.DAY)] + sv[(e, d + i, D.EDUCATION)]) for i in range(5)]
                    model.Add(sum(day_window) <= 4)
                    model.Add(sum(day_window[:4]) + sv[(e, d + 4, D.NIGHT)] <= 4)

            if k > 0:
                for d in range(1, min(6, self.num_days + 1)):
                    prefix_day  = [(sv[(e, dd, D.DAY)] + sv[(e, dd, D.EDUCATION)]) for dd in range(1, d + 1)]
                    prefix_prev = [(sv[(e, dd, D.DAY)] + sv[(e, dd, D.EDUCATION)]) for dd in range(1, d)]
                    model.Add(k + sum(prefix_day)  <= 4)
                    model.Add(k + sum(prefix_prev) + sv[(e, d, D.NIGHT)] <= 4)

    def _c5_daily_staffing(self, model, sv):
        """💡 기관 일일 인원 밸런스. 여기서는 오직 진짜 '주간' 근무자만 카운트합니다."""
        D = ShiftType
        for d in self.days:
            day_sum   = sum(sv[(e, d, D.DAY)]   for e in range(self.n_emp))
            night_sum = sum(sv[(e, d, D.NIGHT)] for e in range(self.n_emp))
            model.Add(day_sum   >= 1);  model.Add(day_sum   <= 3)
            model.Add(night_sum >= 1);  model.Add(night_sum <= 2)

    def _c6_equal_holidays(self, model, sv):
        try:
            import holidays
            kr_holidays = holidays.KR(years=self.year)
        except ImportError:
            kr_holidays = {}

        target_holidays = 0
        for d in self.days:
            date_obj = datetime.date(self.year, self.month, d)
            if date_obj.weekday() >= 5 or date_obj in kr_holidays:
                target_holidays += 1

        D = ShiftType
        for e in range(self.n_emp):
            emp_holiday_sum = sum(sv[(e, d, D.HOLIDAY)] for d in self.days)
            model.Add(emp_holiday_sum == target_holidays)

    def _objective(self, model, sv) -> List:
        D     = ShiftType
        terms = []

        for e, emp in enumerate(self.employees):
            for d in self.days:
                if emp.prefer_day:
                    terms.append(sv[(e, d, D.DAY)]   * 3)
                if emp.prefer_night:
                    terms.append(sv[(e, d, D.NIGHT)] * 3)

        for d in self.days:
            day_s   = model.NewIntVar(0, self.n_emp, f"ds_{d}")
            night_s = model.NewIntVar(0, self.n_emp, f"ns_{d}")
            model.Add(day_s   == sum(sv[(e, d, D.DAY)]   for e in range(self.n_emp)))
            model.Add(night_s == sum(sv[(e, d, D.NIGHT)] for e in range(self.n_emp)))

            b_d2 = model.NewBoolVar(f"d2_{d}")
            model.Add(day_s == 2).OnlyEnforceIf(b_d2)
            model.Add(day_s != 2).OnlyEnforceIf(b_d2.Not())
            terms.append(b_d2 * 5)

            b_n2 = model.NewBoolVar(f"n2_{d}")
            model.Add(night_s == 2).OnlyEnforceIf(b_n2)
            model.Add(night_s != 2).OnlyEnforceIf(b_n2.Not())
            terms.append(b_n2 * 5)

            b_d3 = model.NewBoolVar(f"d3_{d}")
            model.Add(day_s == 3).OnlyEnforceIf(b_d3)
            model.Add(day_s != 3).OnlyEnforceIf(b_d3.Not())
            terms.append(b_d3 * (-3))

        return terms

    def _exclude(self, model, sv, prev: MonthSchedule):
        same = []
        for e, emp in enumerate(self.employees):
            for d in self.days:
                ps = prev.schedule.get(emp.name, {}).get(d)
                if ps in (ShiftType.DAY, ShiftType.NIGHT):
                    same.append(sv[(e, d, ps)])
        if same:
            n_diff = min(3, len(same))
            model.Add(sum(same) <= len(same) - n_diff)
