import streamlit as st
import datetime
import calendar
import pandas as pd
import io
import copy
from models import Employee, FixedSchedule, ShiftType, MonthSchedule
from scheduler import ShiftScheduler
from validator import validate

st.set_page_config(page_title="사회복무요원 근무표 생성기", layout="wide")

# --- 세션 상태 초기화 (화면 전환용) ---
if 'page' not in st.session_state:
    st.session_state.page = 'main'
if 'generated_results' not in st.session_state:
    st.session_state.generated_results = []
if 'selected_idx' not in st.session_state:
    st.session_state.selected_idx = 0
if 'employees' not in st.session_state:
    st.session_state.employees = []

# --- 스타일링 함수 (엑셀 가독성 적용) ---
def color_shifts(val):
    if val == "주간": return 'background-color: #0070C0; color: white; font-weight: bold;'
    if val == "야간": return 'background-color: #FFFF00; color: black; font-weight: bold;'
    if val == "휴일": return 'color: red; font-weight: bold;'
    if val == "연가": return 'background-color: #ED7D31; color: white; font-weight: bold;'
    if val == "특별": return 'background-color: #7030A0; color: white; font-weight: bold;'
    if val == "비번": return 'color: #808080;'
    return ''

# 문자열 ↔ ShiftType 변환용 딕셔너리
SHIFT_MAP = {
    "주간": ShiftType.DAY, "야간": ShiftType.NIGHT, "비번": ShiftType.OFF,
    "휴일": ShiftType.HOLIDAY, "연가": ShiftType.ANNUAL, 
    "특별": ShiftType.SPECIAL, "교육": ShiftType.EDUCATION
}

# ==========================================
# 📺 화면 1: 메인 설정 및 근무표 생성 화면
# ==========================================
def render_main_page():
    st.title("🚀 사회복무요원 근무표 자동화 시스템")
    
    with st.sidebar:
        st.header("⚙️ 기본 설정")
        today = datetime.date.today()
        st.markdown("**생성 연/월 선택**")
        y_col, m_col = st.columns(2)
        year = y_col.selectbox("연도", range(today.year - 1, today.year + 4), index=1, label_visibility="collapsed", format_func=lambda x: f"{x}년", key="year_sel")
        month = m_col.selectbox("월", range(1, 13), index=today.month - 1, label_visibility="collapsed", format_func=lambda x: f"{x}월", key="month_sel")
        
        num_solutions = st.slider("생성할 대안 수", 1, 5, 3, key="num_sol")
        time_limit = st.number_input("탐색 시간 제한(초)", 10, 300, 30, key="time_lim")
        st.session_state.current_year = year
        st.session_state.current_month = month

    _, num_days = calendar.monthrange(year, month)
    month_days = list(range(1, num_days + 1))

    st.header("👥 사회복무요원 관리")
    if st.button("➕ 사회복무요원 추가"):
        st.session_state.employees.append({
            "name": "", "prefer_day": True, "prefer_night": False, 
            "fixed": {"연가": [], "특별": [], "교육": [], "휴일": []}
        })

    cols = st.columns([2, 1, 1, 4, 1])
    cols[0].markdown("**이름**")
    cols[1].markdown("**주간선호**")
    cols[2].markdown("**야간선호**")
    cols[3].markdown("**고정 일정 (지정휴일/연가/특휴/교육)**")
    cols[4].markdown("**삭제**")

    for idx, emp in enumerate(st.session_state.employees):
        c1, c2, c3, c4, c5 = st.columns([2, 1, 1, 4, 1])
        emp['name'] = c1.text_input(f"이름 {idx}", value=emp['name'], label_visibility="collapsed", placeholder="이름 입력")
        emp['prefer_day'] = c2.checkbox(f"주 {idx}", value=emp['prefer_day'], label_visibility="collapsed")
        emp['prefer_night'] = c3.checkbox(f"야 {idx}", value=emp['prefer_night'], label_visibility="collapsed")
        
        old_fixed = emp.get('fixed', {})
        if isinstance(old_fixed, str):
            emp['fixed'] = {"연가": [], "특별": [], "교육": [], "휴일": []}
        else:
            emp['fixed'] = {
                "연가": old_fixed.get("연가", []), "특별": old_fixed.get("특별", []), 
                "교육": old_fixed.get("교육", []), "휴일": old_fixed.get("휴일", [])
            }
            
        total_fixed = len(emp['fixed']['연가']) + len(emp['fixed']['특별']) + len(emp['fixed']['교육']) + len(emp['fixed']['휴일'])
        btn_label = f"📅 일정 관리 (총 {total_fixed}일)" if total_fixed > 0 else "📅 일정 추가"
        
        with c4.popover(btn_label, use_container_width=True):
            st.markdown(f"**{emp['name'] if emp['name'] else '이름 없음'}** 요원 고정 일정")
            valid_hol = [d for d in emp['fixed']['휴일'] if d in month_days]
            valid_ann = [d for d in emp['fixed']['연가'] if d in month_days]
            valid_spe = [d for d in emp['fixed']['특별'] if d in month_days]
            valid_edu = [d for d in emp['fixed']['교육'] if d in month_days]
            
            emp['fixed']['휴일'] = st.multiselect("🔴 지정 휴일", options=month_days, default=valid_hol, key=f"hol_{idx}")
            emp['fixed']['연가'] = st.multiselect("🌴 연가", options=month_days, default=valid_ann, key=f"ann_{idx}")
            emp['fixed']['특별'] = st.multiselect("🎁 특별휴가", options=month_days, default=valid_spe, key=f"spe_{idx}")
            emp['fixed']['교육'] = st.multiselect("📚 교육", options=month_days, default=valid_edu, key=f"edu_{idx}")

        if c5.button("🗑️", key=f"del_{idx}"):
            st.session_state.employees.pop(idx)
            st.rerun()

    st.header("📋 이월 데이터 (전달 마지막 4일)")
    carryover = {}
    if st.session_state.employees:
        for emp in st.session_state.employees:
            if emp['name'].strip():
                st.subheader(f"📍 {emp['name']}")
                r_cols = st.columns(4)
                carryover[emp['name']] = {}
                for i, d in enumerate([-3, -2, -1, 0]):
                    val = r_cols[i].selectbox(f"{d}일 근무", ["주간", "야간", "비번", "휴일"], index=3, key=f"carry_{emp['name']}_{d}")
                    carryover[emp['name']][d] = SHIFT_MAP[val]

    st.divider()
    if st.button("🚀 근무표 생성하기", type="primary", use_container_width=True):
        if not st.session_state.employees:
            st.error("사회복무요원을 최소 한 명 이상 추가해 주세요.")
        else:
            final_emps = []
            for e in st.session_state.employees:
                if not e['name'].strip(): continue
                fixed_list = []
                for d in e['fixed']['휴일']: fixed_list.append(FixedSchedule(d, ShiftType.HOLIDAY))
                for d in e['fixed']['연가']: fixed_list.append(FixedSchedule(d, ShiftType.ANNUAL))
                for d in e['fixed']['특별']: fixed_list.append(FixedSchedule(d, ShiftType.SPECIAL))
                for d in e['fixed']['교육']: fixed_list.append(FixedSchedule(d, ShiftType.EDUCATION))
                final_emps.append(Employee(e['name'], e['prefer_day'], e['prefer_night'], fixed_list))
            
            with st.spinner("최적의 근무표를 계산 중입니다..."):
                scheduler = ShiftScheduler(year, month, final_emps, carryover, num_solutions, time_limit)
                results = scheduler.solve()
                
                if not results:
                    st.error("조건에 맞는 해를 찾지 못했습니다.")
                else:
                    st.session_state.generated_results = results
                    st.success("🎉 근무표 생성이 완료되었습니다! 아래 대안을 선택하여 상세 화면으로 이동하세요.")
                    
    # 💡 생성된 대안 버튼 목록 표시 (페이지 이동 유도)
    if st.session_state.generated_results:
        st.markdown("### 📊 생성된 근무표 확인하기")
        btn_cols = st.columns(len(st.session_state.generated_results))
        for idx, res in enumerate(st.session_state.generated_results):
            if btn_cols[idx].button(f"🔍 {res.solution_label}안 상세 보기\n(점수: {res.score})", use_container_width=True):
                st.session_state.selected_idx = idx
                st.session_state.page = 'detail'
                st.rerun()

# ==========================================
# 📺 화면 2: 상세 뷰어 및 편집기
# ==========================================
def render_detail_page():
    res = st.session_state.generated_results[st.session_state.selected_idx]
    year = st.session_state.current_year
    month = st.session_state.current_month
    _, num_days = calendar.monthrange(year, month)
    month_days = list(range(1, num_days + 1))

    # 상단 네비게이션 및 타이틀
    c1, c2 = st.columns([1, 4])
    if c1.button("◀ 이전 설정으로 돌아가기"):
        st.session_state.page = 'main'
        st.rerun()
    c2.title(f"🗓️ {year}년 {month}월 근무표 [{res.solution_label}안]")

    # 화면 2 상호작용 토글 버튼들
    ctrl1, ctrl2, ctrl3 = st.columns(3)
    show_details = ctrl1.toggle("📊 자세히 보기 (통계 및 합계 표시)", value=False)
    edit_mode = ctrl2.toggle("✏️ 수동 수정 모드", value=False)
    
    st.info("💡 수정 모드를 켜면 표를 더블 클릭하여 직접 스케줄을 변경할 수 있습니다. (색상 효과는 뷰어 모드에서만 지원됩니다)")

    # 1. 데이터프레임 구성 로직
    table_data = []
    for emp in res.employees:
        row = {"이름": emp.name}
        for d in month_days:
            shift = res.get_shift(emp.name, d)
            row[f"{d}일"] = shift.value if shift else ""
            
        if show_details:
            stats = res.get_stats(emp.name)
            row["주간"] = stats['주간']
            row["야간"] = stats['야간']
            row["비번"] = stats['비번']
            row["휴일"] = stats['휴일']
            row["연가"] = stats['연가']
            row["특별"] = stats['특별']
            row["교육"] = stats['교육']
            row["합계"] = sum([stats[k] for k in ['주간', '야간', '비번', '휴일', '연가', '특별', '교육']])
        table_data.append(row)

    if show_details:
        day_count_row = {"이름": "주간인원"}
        night_count_row = {"이름": "야간인원"}
        for d in month_days:
            day_count_row[f"{d}일"] = str(sum(1 for emp in res.employees if res.get_shift(emp.name, d) == ShiftType.DAY))
            night_count_row[f"{d}일"] = str(sum(1 for emp in res.employees if res.get_shift(emp.name, d) == ShiftType.NIGHT))
        for col in ["주간", "야간", "비번", "휴일", "연가", "특별", "교육", "합계"]:
            day_count_row[col] = ""
            night_count_row[col] = ""
        table_data.extend([day_count_row, night_count_row])

    df = pd.DataFrame(table_data)

    # 2. 표 출력 및 수정 로직
    if edit_mode:
        # 수정 모드: st.data_editor 사용 (드롭다운 적용)
        config = {"이름": st.column_config.TextColumn("이름", disabled=True)}
        for d in month_days:
            config[f"{d}일"] = st.column_config.SelectboxColumn(
                f"{d}일", options=["주간", "야간", "비번", "휴일", "연가", "특별", "교육"]
            )
        # 통계 칸은 수정 불가
        for col in ["주간", "야간", "비번", "휴일", "연가", "특별", "교육", "합계"]:
            config[col] = st.column_config.TextColumn(col, disabled=True)

        edited_df = st.data_editor(df, column_config=config, use_container_width=True, hide_index=True)
        
        # 적용 및 검사 버튼
        if st.button("💾 변경사항 적용 및 제약 검사", type="primary"):
            # 수정한 데이터프레임을 다시 MonthSchedule 객체로 변환
            new_schedule = {}
            for _, row in edited_df.iterrows():
                name = row["이름"]
                if name in ["주간인원", "야간인원"]: continue
                new_schedule[name] = {}
                for d in month_days:
                    val = row[f"{d}일"]
                    if val and val in SHIFT_MAP:
                        new_schedule[name][d] = SHIFT_MAP[val]
            
            # 임시 객체 생성 및 검증
            temp_res = MonthSchedule(year, month, num_days, res.employees, new_schedule, 0, res.solution_label)
            violations = validate(temp_res)
            
            if violations:
                st.error("🚨 앗! 수정한 스케줄에 제약 위반(Hard Constraint)이 발견되었습니다.")
                for name, day, msg in violations:
                    st.warning(f"**[{name} 요원 | {day}일]** {msg}")
            else:
                st.success("✅ 완벽합니다! 제약 위반이 없습니다.")
                # 실제 데이터에 덮어쓰기
                st.session_state.generated_results[st.session_state.selected_idx] = temp_res
                st.rerun()

    else:
        # 뷰어 모드: 색상 입힌 엑셀 스타일 출력
        styled_df = df.style.map(color_shifts)
        st.dataframe(styled_df, use_container_width=True, hide_index=True)

    # 3. 엑셀 다운로드 (항상 표시)
    st.divider()
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name=f"{res.solution_label}안")
    
    st.download_button(
        label="📥 현재 스케줄 엑셀(Excel) 다운로드",
        data=buffer.getvalue(),
        file_name=f"근무표_{year}년_{month}월.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

# --- 앱 실행(라우팅) ---
if st.session_state.page == 'main':
    render_main_page()
elif st.session_state.page == 'detail':
    render_detail_page()
