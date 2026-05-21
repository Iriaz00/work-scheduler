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

# --- 세션 상태 초기화 (화면 전환 및 데이터 보존용) ---
if 'page' not in st.session_state:
    st.session_state.page = 'main'
if 'generated_results' not in st.session_state:
    st.session_state.generated_results = []
if 'selected_idx' not in st.session_state:
    st.session_state.selected_idx = 0
if 'employees' not in st.session_state:
    st.session_state.employees = []
if 'selected_emp_name' not in st.session_state:
    st.session_state.selected_emp_name = ""
if 'carryover_data' not in st.session_state:
    st.session_state.carryover_data = {}

# --- 스타일링 관련 함수 및 맵핑 ---
def color_shifts(val):
    v = str(val).strip()
    style = 'text-align: center; '
    if v == "주": return style + 'background-color: #0070C0; color: white; font-weight: bold;'
    if v == "야": return style + 'background-color: #FFFF00; color: black; font-weight: bold;'
    if v == "휴": return style + 'color: #FF4B4B; font-weight: bold;'
    if v == "연": return style + 'background-color: #ED7D31; color: white; font-weight: bold;'
    if v == "특": return style + 'background-color: #7030A0; color: white; font-weight: bold;'
    if v == "교": return style + 'background-color: #00B050; color: white; font-weight: bold;'
    if v == "비": return style + 'color: #808080;'
    
    if v in ["토", "일"] or "(휴)" in v:
        return style + 'background-color: #FFCCCC; color: #FF0000; font-weight: bold;'
    if v in ["월", "화", "수", "목", "금"]:
        return style + 'background-color: #F0F2F6; color: black; font-weight: bold;'
    return style

# 달력 셀 내부 전용 색상 맵 (HTML 렌더링용)
CAL_COLOR_MAP = {
    "주": "background-color: #0070C0; color: white;",
    "야": "background-color: #FFFF00; color: black;",
    "휴": "background-color: #FFD2D2; color: #FF0000; font-weight: bold;",
    "연": "background-color: #ED7D31; color: white;",
    "특": "background-color: #7030A0; color: white;",
    "교": "background-color: #00B050; color: white;",
    "비": "background-color: #F0F0F0; color: #808080;"
}

SHIFT_MAP = {
    "주": ShiftType.DAY, "야": ShiftType.NIGHT, "비": ShiftType.OFF,
    "휴": ShiftType.HOLIDAY, "연": ShiftType.ANNUAL, 
    "특": ShiftType.SPECIAL, "교": ShiftType.EDUCATION
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
        st.session_state.num_solutions = num_solutions
        st.session_state.time_limit = time_limit

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
                    val = r_cols[i].selectbox(f"{d}일 근무", ["주", "야", "비", "휴"], index=3, key=f"carry_{emp['name']}_{d}")
                    carryover[emp['name']][d] = SHIFT_MAP[val]
        st.session_state.carryover_data = carryover

    st.divider()
    if st.button("🚀 근무표 생성하기", type="primary", use_container_width=True):
        if not st.session_state.employees:
            st.error("사회복무요원을 최소 한 명 이상 추가해 주세요.")
        else:
            run_scheduling_engine()

    if st.session_state.generated_results:
        st.markdown("### 📊 생성된 근무표 확인하기")
        btn_cols = st.columns(len(st.session_state.generated_results))
        for idx, res in enumerate(st.session_state.generated_results):
            if btn_cols[idx].button(f"🔍 {res.solution_label}안 상세 보기\n(점수: {res.score})", use_container_width=True):
                st.session_state.selected_idx = idx
                st.session_state.page = 'detail'
                st.rerun()

# 스케줄러 구동 공통 함수 (재생성 시에도 활용)
def run_scheduling_engine():
    year = st.session_state.current_year
    month = st.session_state.current_month
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
        scheduler = ShiftScheduler(year, month, final_emps, st.session_state.carryover_data, st.session_state.num_solutions, st.session_state.time_limit)
        results = scheduler.solve()
        if results:
            st.session_state.generated_results = results
            return True
        return False

# ==========================================
# 📺 화면 2: 전체 스케줄 뷰어 및 편집기
# ==========================================
def render_detail_page():
    res = st.session_state.generated_results[st.session_state.selected_idx]
    year = st.session_state.current_year
    month = st.session_state.current_month
    _, num_days = calendar.monthrange(year, month)
    month_days = list(range(1, num_days + 1))

    c1, c2 = st.columns([1, 4])
    if c1.button("◀ 이전 설정으로 돌아가기"):
        st.session_state.page = 'main'
        st.rerun()
    c2.title(f"🗓️ {year}년 {month}월 근무표 [{res.solution_label}안]")

    ctrl1, ctrl2, _ = st.columns(3)
    show_details = ctrl1.toggle("📊 자세히 보기 (통계 및 합계 표시)", value=False)
    edit_mode = ctrl2.toggle("✏️ 수동 수정 모드", value=False)
    
    st.info("💡 수정 모드를 켜면 표를 직접 스케줄을 변경할 수 있습니다. 아래 '요원별 상세 달력' 버튼을 누르면 인물별 캘린더 화면으로 이동합니다.")

    table_data = []
    
    # 요일 행 생성
    day_row = {"이름": "요일"}
    try:
        import holidays
        kr_holidays = holidays.KR(years=year)
    except ImportError:
        kr_holidays = {}
        
    for d in month_days:
        date_obj = datetime.date(year, month, d)
        wd = ["월", "화", "수", "목", "금", "토", "일"][date_obj.weekday()]
        is_off = (date_obj.weekday() >= 5) or (date_obj in kr_holidays)
        day_row[f"{d}일"] = f"{wd}(휴)" if is_off and date_obj.weekday() < 5 else wd
            
    for col in ["주간", "야간", "비번", "휴일", "연가", "특별", "교육", "합계"]:
        day_row[col] = None
    table_data.append(day_row)
    
    # 직원 스케줄 생성
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
    df.set_index("이름", inplace=True)

    if edit_mode:
        config = {}
        for d in month_days:
            config[f"{d}일"] = st.column_config.SelectboxColumn(
                f"{d}일", options=["주", "야", "비", "휴", "연", "특", "교", "월", "화", "수", "목", "금", "토", "일", "월(휴)", "화(휴)", "수(휴)", "목(휴)", "금(휴)"]
            )
        for col in ["주간", "야간", "비번", "휴일", "연가", "특별", "교육", "합계"]:
            config[col] = st.column_config.TextColumn(col, disabled=True)

        edited_df = st.data_editor(df, column_config=config, use_container_width=True)
        
        if st.button("💾 변경사항 적용 및 제약 검사", type="primary"):
            new_schedule = {}
            for name, row in edited_df.iterrows():
                if name in ["요일", "주간인원", "야간인원"]: continue
                new_schedule[name] = {}
                for d in month_days:
                    val = row[f"{d}일"]
                    if val and val in SHIFT_MAP:
                        new_schedule[name][d] = SHIFT_MAP[val]
            
            temp_res = MonthSchedule(year, month, num_days, res.employees, new_schedule, 0, res.solution_label)
            violations = validate(temp_res)
            
            if violations:
                st.error("🚨 제약 위반(Hard Constraint)이 발견되었습니다.")
                for name, day, msg in violations:
                    st.warning(f"**[{name} 요원 | {day}일]** {msg}")
            else:
                st.success("✅ 제약 검사 통과! 수정사항이 동적으로 반영되었습니다.")
                st.session_state.generated_results[st.session_state.selected_idx] = temp_res
                st.rerun()
    else:
        styled_df = df.style.map(color_shifts)
        st.dataframe(styled_df, use_container_width=True)

    # 💡 2번 화면 하단: 요원 이름들을 버튼으로 나열 (화면 3으로 연결)
    st.markdown("---")
    st.markdown("### 🔍 요원별 인물 상세 정보 (달력 보기)")
    st.caption("아래 요원의 이름을 클릭하면 해당 요원의 한 달 스케줄 달력과 상세 설정을 편집할 수 있는 화면으로 이동합니다.")
    
    # 인원수에 맞게 컬럼을 쪼개서 가로로 이름 버튼들을 배치
    emp_names = [emp.name for emp in res.employees]
    if emp_names:
        btn_cols = st.columns(min(8, len(emp_names))) # 한 줄에 최대 8명씩 배치
        for idx, name in enumerate(emp_names):
            col_target = btn_cols[idx % 8]
            if col_target.button(f"👤 {name}", use_container_width=True, key=f"jump_{name}"):
                st.session_state.selected_emp_name = name
                st.session_state.page = 'individual'
                st.rerun()

    # 엑셀 다운로드
    st.divider()
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        df.reset_index().to_excel(writer, index=False, sheet_name=f"{res.solution_label}안")
    st.download_button(
        label="📥 현재 스케줄 엑셀(Excel) 다운로드", data=buffer.getvalue(),
        file_name=f"근무표_{year}년_{month}월_{res.solution_label}안.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

# ==========================================
# 📺 화면 3: <인물별 정보> (개인 상세 뷰어 및 달력)
# ==========================================
def render_individual_page():
    year = st.session_state.current_year
    month = st.session_state.current_month
    emp_name = st.session_state.selected_emp_name
    res = st.session_state.generated_results[st.session_state.selected_idx]
    
    _, num_days = calendar.monthrange(year, month)
    month_days = list(range(1, num_days + 1))

    # 세션 상태에서 실제 직원 데이터 매칭 기동
    emp_idx = next((i for i, e in enumerate(st.session_state.employees) if e['name'] == emp_name), None)
    
    c1, c2 = st.columns([1, 4])
    if c1.button("◀ 전체 근무표로 돌아가기"):
        st.session_state.page = 'detail'
        st.rerun()
    c2.title(f"👤 {emp_name} 요원의 개인 상세 스케줄 및 관리")

    if emp_idx is None:
        st.error("해당 요원의 기본 정보를 세션에서 찾을 수 없습니다.")
        return

    emp_data = st.session_state.employees[emp_idx]

    # 🛠️ 상단: 개인 설정 및 고정 일정 수정 레이아웃
    st.markdown("### ⚙️ 개인 근무 제약 및 선호도 수정")
    exp1 = st.expander("🛠️ 이 요원의 선호도 및 고정일정 변경하기 (클릭하여 열기)", expanded=False)
    with exp1:
        cc1, cc2 = st.columns(2)
        emp_data['prefer_day'] = cc1.checkbox("주간 근무 선호", value=emp_data['prefer_day'], key=f"ind_pref_d")
        emp_data['prefer_night'] = cc2.checkbox("야간 근무 선호", value=emp_data['prefer_night'], key=f"ind_pref_n")
        
        st.markdown("**고정 일정 관리**")
        emp_data['fixed']['휴일'] = st.multiselect("🔴 지정 휴일 선택", options=month_days, default=emp_data['fixed'].get('휴일', []), key="ind_hol")
        emp_data['fixed']['연가'] = st.multiselect("🌴 연가 선택", options=month_days, default=emp_data['fixed'].get('연가', []), key="ind_ann")
        emp_data['fixed']['특별'] = st.multiselect("🎁 특별휴가 선택", options=month_days, default=emp_data['fixed'].get('특별', []), key="ind_spe")
        emp_data['fixed']['교육'] = st.multiselect("📚 교육 선택", options=month_days, default=emp_data['fixed'].get('교육', []), key="ind_edu")
        
        action_c1, action_c2 = st.columns(2)
        if action_c1.button("💾 변경사항 적용 (저장)", type="primary", use_container_width=True):
            st.success(f"💾 {emp_name} 요원의 선호 설정이 데이터베이스에 임시 반영되었습니다.")
            
        if action_c2.button("🔄 이 설정 바탕으로 근무표 전체 재생성 (리스케줄링)", use_container_width=True):
            if run_scheduling_engine():
                st.success("🎉 개인 최적화 변경사항을 반영하여 근무표가 완벽하게 리스케줄링(재생성) 되었습니다!")
                st.rerun()
            else:
                st.error("🚨 새로운 조건 제약이 너무 무거워 알고리즘 엔진이 해를 찾지 못했습니다. 제약을 완화해 주세요.")

    # 🗓️ 하단: 한 달 스케줄 달력(Calendar) 시각화 기동
    st.markdown("---")
    st.markdown(f"### 🗓️ {month}월 스케줄 캘린더 구동 뷰어")

    try:
        import holidays
        kr_holidays = holidays.KR(years=year)
    except ImportError:
        kr_holidays = {}

    # 달력 틀 구성을 위한 파이썬 내부 달력 라이브러리 연동
    # calendar.monthrange는 월요일=0, ..., 일요일=6 반환.
    # 한국형 달력(일요일 시작) 형태로 칸 맞춤을 위해 전처리 진행
    first_weekday, _ = calendar.monthrange(year, month)
    start_blank = (first_weekday + 1) % 7 # 일요일=0 기준으로 공백 칸 개수 환산

    cal_days = [None] * start_blank + month_days
    while len(cal_days) % 7 != 0:
        cal_days.append(None)

    # 달력 헤더 출력
    headers = ["일", "월", "화", "수", "목", "금", "토"]
    h_cols = st.columns(7)
    for i, h in enumerate(headers):
        color = "#FF4B4B" if i == 0 else ("#0070C0" if i == 6 else "white")
        h_cols[i].markdown(f"<div style='text-align: center; background-color: #31333F; color: {color}; padding: 5px; font-weight: bold; border-radius: 4px;'>{h}</div>", unsafe_html=True)

    # 주 단위 렌더링
    for week_idx in range(len(cal_days) // 7):
        week_days = cal_days[week_idx*7 : (week_idx+1)*7]
        w_cols = st.columns(7)
        
        for day_pos, d in enumerate(week_days):
            if d is None:
                w_cols[day_pos].markdown("<div style='min-height: 80px;'></div>", unsafe_html=True)
            else:
                date_obj = datetime.date(year, month, d)
                shift_val = res.get_shift(emp_name, d)
                shift_str = shift_val.value if shift_val else ""
                
                # 오늘 요일 및 공휴일 여부 체크에 따른 날짜 글씨 색상
                is_holiday = (day_pos == 0) or (date_obj in kr_holidays)
                is_saturday = (day_pos == 6)
                day_color = "#FF4B4B" if is_holiday else ("#0070C0" if is_saturday else "white")
                
                # 근무 타입에 따른 동적 백그라운드 색상 바인딩
                cell_style = CAL_COLOR_MAP.get(shift_str, "background-color: #262730; color: white;")
                
                # 예쁜 격자형 카드 컴포넌트로 마크다운 조립 출력
                html_box = f"""
                <div style="
                    border: 1px solid #464855; 
                    border-radius: 6px; 
                    padding: 8px; 
                    min-height: 85px; 
                    margin-top: 6px;
                    background-color: #1E1E24;
                ">
                    <span style="color: {day_color}; font-weight: bold; font-size: 14px;">{d}</span>
                    <div style="
                        {cell_style}
                        text-align: center; 
                        margin-top: 10px; 
                        padding: 4px; 
                        font-size: 16px; 
                        font-weight: bold; 
                        border-radius: 4px;
                        box-shadow: 1px 1px 3px rgba(0,0,0,0.3);
                    ">
                        {shift_str if shift_str else '비'}
                    </div>
                </div>
                """
                w_cols[day_pos].markdown(html_box, unsafe_html=True)

# --- 메인 라우터 앱 흐름 기동 ---
if st.session_state.page == 'main':
    render_main_page()
elif st.session_state.page == 'detail':
    render_detail_page()
elif st.session_state.page == 'individual':
    render_individual_page()
