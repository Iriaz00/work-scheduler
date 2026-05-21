
from typing import List, Set, Tuple
from models import MonthSchedule, ShiftType

Violation = Tuple[str, int, str]   # (직원명, 날짜, 위반 내용)


def validate(result: MonthSchedule) -> List[Violation]:
    """
    근무표 전체를 검사하여 하드 제약 위반 목록 반환.
    수동 편집 후 [적용] 버튼 클릭 시 호출.
    """
    vs: List[Violation] = []
    schedule = result.schedule
    N = result.num_days
    D = ShiftType

    for name, shifts in schedule.items():
        s = lambda d: shifts.get(d)

        for day in range(1, N + 1):
            cur = s(day)

            # ── 야비휴 세트 ─────────────────────────────
            if cur == D.NIGHT:
                if day + 1 <= N and s(day + 1) != D.OFF:
                    vs.append((name, day,
                        f"야간 다음날({day+1}일)이 비번이어야 합니다"))
                if day + 2 <= N and s(day + 2) != D.HOLIDAY:
                    vs.append((name, day,
                        f"야간 이틀 후({day+2}일)이 휴일이어야 합니다"))

            if cur == D.OFF:
                if day - 1 >= 1 and s(day - 1) != D.NIGHT:
                    vs.append((name, day,
                        "비번은 야간 직후에만 가능합니다"))

            # ── 주간 연속 한도 ───────────────────────────
            if cur == D.DAY and s(day - 1) != D.DAY:   # 연속 시작점
                run = 0
                next_after = None
                for dd in range(day, min(day + 6, N + 2)):
                    if s(dd) == D.DAY:
                        run += 1
                    else:
                        next_after = s(dd)
                        break
                if run > 4:
                    vs.append((name, day,
                        f"주간 {run}일 연속 (최대 4일)"))
                elif run > 3 and next_after == D.NIGHT:
                    vs.append((name, day,
                        f"주간 {run}일 연속 후 야간 배정 (최대 3일)"))

    # ── 일일 인원 ──────────────────────────────────
    for day in range(1, N + 1):
        day_cnt   = sum(1 for sh in schedule.values()
                        if sh.get(day) == D.DAY)
        night_cnt = sum(1 for sh in schedule.values()
                        if sh.get(day) == D.NIGHT)
        if not (1 <= day_cnt <= 3):
            vs.append(("전체", day,
                f"주간 인원 {day_cnt}명 (허용: 1~3명)"))
        if not (1 <= night_cnt <= 2):
            vs.append(("전체", day,
                f"야간 인원 {night_cnt}명 (허용: 1~2명)"))

    return vs


def violation_cells(vs: List[Violation]) -> Set[Tuple[str, int]]:
    """위반 발생 셀 집합 반환 → UI 빨간 표시용"""
    return {(name, day) for name, day, _ in vs}
