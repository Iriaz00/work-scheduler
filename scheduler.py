
from __future__ import annotations
from typing import Dict, List, Optional, Tuple
import calendar as cal_module

from ortools.sat.python import cp_model
from models import ALL_SHIFTS, Employee, FixedSchedule, MonthSchedule, ShiftType


class ShiftScheduler:
    """
    OR-Tools CP-SAT 기반 교대 근무표 자동 생성 엔진

    [하드 제약]
      C1. 1인 1일 1근무 유형
      C2. 야-비-휴 세트 강제  ※ 월말 야간은 비·휴를 다음달 이월로 처리
      C3. 주간 연속 최대 4일 (이월 포함)
      C4. 주간→야간 전환 시 주간 최대 3일 (이월 포함)
      C5. 일일 주간 1~3명, 야간 1~2명

    [소프트 제약 - 목적함수]
      S1. 주간/야간 선호도 반영 (+3점)
      S2. 주간 2명·야간 2명 배정 시 최적 (+5점)
      S3. 주간 3명 쏠림 페널티 (-3점)
    """

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
        self.carryover     = carryover or {}
        self.num_solutions = num_solutions
        self.time_limit    = time_limit

        self.num_days = cal_module.monthrange(year, month)[1]
        self.days     = list(range(1, self.num_days + 1))
        self.n_emp    = len(self.employees)

        self._preprocess_carryover()

    # ═══════════════════════════════════════════════
    # 이월(Carry-over) 전처리
    # ═══════════════════════════════════════════════

    def _carry(self, emp_name: str, day: int) -> Optional[ShiftType]:
        return self.carryover.get(emp_name, {}).get(day)

    def _carry_consec_days(self, emp_name: str) -> int:
        """전월 말미 연속 주간 근무 일수 (최대 4)"""
        cnt = 0
        for d in (0, -1, -2, -3):
            if self._carry(emp_name, d) == ShiftType.DAY:
                cnt += 1
            else:
                break
        return cnt

    def _preprocess_carryover(self):
        """
        전월 야간 세트가 당월 초에 걸치는 경우 고정 배정 자동 추가

          전월 day 0  = 야  →  당월 day 1 = 비,  day 2 = 휴
          전월 day -1 = 야  →  당월 day 1 = 휴   (day 0 비번은 이미 이월)
        """
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

    # ═══════════════════════════════════════════════
    # 공개 인터페이스
    # ═══════════════════════════════════════════════

    def solve(self) -> List[MonthSchedule]:
        """A/B/C안 순서대로 최적해 탐색 후 반환"""
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

    # ═══════════════════════════════════════════════
    # 단일 해 탐색
    # ═══════════════════════════════════════════════

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

        for p in prev_results:
            self._exclude(model, sv, p)

        model.Maximize(cp_model.LinearExpr.Sum(self._objective(model, sv)))

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = self.time_limit
        solver.parameters.log_search_progress = False

        status     = solver.Solve(model)
        status_str = self._STATUS.get(status, f"코드:{status}")
        print(status_str, end="  ")

        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return None

        # 결과 추출
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

    # ═══════════════════════════════════════════════
    # 변수 생성
    # ═══════════════════════════════════════════════

    def _create_vars(self, model: cp_model.CpModel) -> Dict:
        sv: Dict[Tuple, cp_model.IntVar] = {}
        for e, emp in enumerate(self.employees):
            for d in self.days:
                fixed = emp.get_fixed_shift(d)
                for s in ALL_SHIFTS:
                    var = model.NewBoolVar(f"e{e}_d{d}_{s.value}")
                    if fixed is not None:
                        model.Add(var == (1 if s == fixed else 0))
                    sv[(e, d, s)] = var
        return sv

    # ═══════════════════════════════════════════════
    # 하드 제약 C1 ~ C5
    # ═══════════════════════════════════════════════

    def _c1_one_shift_per_day(self, model, sv):
        """C1: 1인 1일 정확히 1개 근무 유형"""
        for e in range(self.n_emp):
            for d in self.days:
                model.AddExactlyOne([sv[(e, d, s)] for s in ALL_SHIFTS])

    def _c2_night_sequence(self, model, sv):
        """
        C2: 야-비-휴 세트 강제

          ① 야[d]  → 비[d+1]      당월 내에서만 강제
          ② 야[d]  → 휴[d+2]      당월 내에서만 강제
          ③ 비[d]  → 야[d-1]      비번은 야간 직후에만 가능
          ④ 월말 야간 허용         비·휴가 다음달로 넘어가면 이월 처리
                                   (기존 night==0 강제 제거 → 핵심 버그 수정)
        """
        D = ShiftType
        for e, emp in enumerate(self.employees):
            carry = self.carryover.get(emp.name, {})

            for d in self.days:
                night = sv[(e, d, D.NIGHT)]
                off_d = sv[(e, d, D.OFF)]

                # ① 야[d] → 비[d+1]  (당월 내에서만)
                if d + 1 in self.days:
                    model.AddImplication(night, sv[(e, d + 1, D.OFF)])
                # d가 마지막날 → 비번은 다음달 이월, 당월 제약 없음

                # ② 야[d] → 휴[d+2]  (당월 내에서만)
                if d + 2 in self.days:
                    model.AddImplication(night, sv[(e, d + 2, D.HOLIDAY)])
                # d+2가 다음달 → 휴일은 다음달 이월, 당월 제약 없음

                # ③ 비[d] → 야[d-1]  (비번은 야간 직후에만)
                if d - 1 in self.days:
                    model.AddImplication(off_d, sv[(e, d - 1, D.NIGHT)])
                else:
                    # d=1: 이월 데이터에서 전날 야간 여부 확인
                    if carry.get(0) != D.NIGHT:
                        model.Add(off_d == 0)

    def _c3_c4_consecutive_limits(self, model, sv):
        """
        C3: 주간 연속 최대 4일
        C4: 주간 직후 야간 배정 시 주간 최대 3일

        ─ 월 내부 슬라이딩 윈도우 (5일 창) ──────────────────
          C3: Σ 주[d..d+4]            ≤ 4
          C4: Σ 주[d..d+3] + 야[d+4] ≤ 4

        ─ 월 경계 (이월 연속 주간 k일 포함) ─────────────────
          C3: k + Σ 주[1..d]              ≤ 4
          C4: k + Σ 주[1..d-1] + 야[d]   ≤ 4
        """
        D = ShiftType
        for e, emp in enumerate(self.employees):
            k = self._carry_consec_days(emp.name)

            # ── 월 내부 슬라이딩 윈도우 ─────────────────────
            for d in range(1, self.num_days + 1):
                if d + 4 <= self.num_days:
                    day_window = [sv[(e, d + i, D.DAY)] for i in range(5)]
                    model.Add(sum(day_window) <= 4)                               # C3
                    model.Add(sum(day_window[:4]) + sv[(e, d + 4, D.NIGHT)] <= 4) # C4

            # ── 월 경계 (이월 연속 k일 포함, 첫 5일) ────────
            if k > 0:
                for d in range(1, min(6, self.num_days + 1)):
                    prefix_day  = [sv[(e, dd, D.DAY)] for dd in range(1, d + 1)]
                    prefix_prev = [sv[(e, dd, D.DAY)] for dd in range(1, d)]

                    model.Add(k + sum(prefix_day)  <= 4)                          # C3
                    model.Add(k + sum(prefix_prev) + sv[(e, d, D.NIGHT)] <= 4)   # C4

    def _c5_daily_staffing(self, model, sv):
        """C5: 일일 주간 1~3명, 야간 1~2명"""
        D = ShiftType
        for d in self.days:
            day_sum   = sum(sv[(e, d, D.DAY)]   for e in range(self.n_emp))
            night_sum = sum(sv[(e, d, D.NIGHT)] for e in range(self.n_emp))
            model.Add(day_sum   >= 1);  model.Add(day_sum   <= 3)
            model.Add(night_sum >= 1);  model.Add(night_sum <= 2)

    # ═══════════════════════════════════════════════
    # 소프트 제약 (목적함수)
    # ═══════════════════════════════════════════════

    def _objective(self, model, sv) -> List:
        D     = ShiftType
        terms = []

        # S1: 선호도 반영
        for e, emp in enumerate(self.employees):
            for d in self.days:
                if emp.prefer_day:
                    terms.append(sv[(e, d, D.DAY)]   * 3)
                if emp.prefer_night:
                    terms.append(sv[(e, d, D.NIGHT)] * 3)

        # S2·S3: 일일 인원 최적화
        for d in self.days:
            day_s   = model.NewIntVar(0, self.n_emp, f"ds_{d}")
            night_s = model.NewIntVar(0, self.n_emp, f"ns_{d}")
            model.Add(day_s   == sum(sv[(e, d, D.DAY)]   for e in range(self.n_emp)))
            model.Add(night_s == sum(sv[(e, d, D.NIGHT)] for e in range(self.n_emp)))

            b_d2 = model.NewBoolVar(f"d2_{d}")
            model.Add(day_s == 2).OnlyEnforceIf(b_d2)
            model.Add(day_s != 2).OnlyEnforceIf(b_d2.Not())
            terms.append(b_d2 * 5)      # 주간 2명 = 최적 (+5)

            b_n2 = model.NewBoolVar(f"n2_{d}")
            model.Add(night_s == 2).OnlyEnforceIf(b_n2)
            model.Add(night_s != 2).OnlyEnforceIf(b_n2.Not())
            terms.append(b_n2 * 5)      # 야간 2명 = 최적 (+5)

            b_d3 = model.NewBoolVar(f"d3_{d}")
            model.Add(day_s == 3).OnlyEnforceIf(b_d3)
            model.Add(day_s != 3).OnlyEnforceIf(b_d3.Not())
            terms.append(b_d3 * (-3))   # 주간 3명 = 쏠림 (-3)

        return terms

    # ═══════════════════════════════════════════════
    # 이전 해 배제
    # ═══════════════════════════════════════════════

    def _exclude(self, model, sv, prev: MonthSchedule):
        """이전 해와 최소 3개의 주간/야간 배정이 달라야 함"""
        same = []
        for e, emp in enumerate(self.employees):
            for d in self.days:
                ps = prev.schedule.get(emp.name, {}).get(d)
                if ps in (ShiftType.DAY, ShiftType.NIGHT):
                    same.append(sv[(e, d, ps)])
        if same:
            n_diff = min(3, len(same))
            model.Add(sum(same) <= len(same) - n_diff)
