import streamlit as st
import datetime
import calendar
import pandas as pd
import io
import copy
import json
from models import Employee, FixedSchedule, ShiftType, MonthSchedule
from scheduler import ShiftScheduler
from validator import validate

st.set_page_config(page_title="사회복무요원 근무표 생성기", layout="wide")

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
if 'preset_carryover' not in st.session_state:
    st.session_state.preset_carryover = {}

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

REVERSE_SHIFT_MAP = {
    ShiftType.DAY: "주", ShiftType.NIGHT: "야", ShiftType.OFF: "비",
    ShiftType.HOLIDAY: "휴", ShiftType.ANNUAL: "휴", 
    ShiftType.SPECIAL: "휴", ShiftType.EDUCATION: "휴"
}

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

        st.markdown("---")
        st.header("💾 인원 및 설정 데이터 관리")
        
        uploaded_file = st.file_uploader("📂 설정 파일(.json) 불러오기", type=["json"])
        if uploaded_file is not None:
            if st.button("데이터 적용하기", use_container_width=True):
                try:
                    data = json.load(uploaded_file)
                    st.session_state.employees = data.get("employees", [])
                    st.session_state.preset_carryover = data.get("carryover", {})
                    st.success("✅ 설정을 성공적으로 불러왔습니다!")
                    st.rerun()
                except Exception as e:
                    st.error("파일을 읽는 중 오류가 발생했습니다.")
        
        if st.button("🗑️ 모든 인원 초기화", use_container_width=True):
            st.session_state.employees = []
            st.session_state.preset_carryover = {}
            st.rerun()

    _, num_days = calendar.monthrange(year, month)
    month_days = list(range(1, num_days + 1))

    st.header("👥 사회복무요원 관리")
    if st.button("➕ 사회복무요원 추가"):
        st.session_state.employees.append({
            "name": "", "prefer_day": True, "prefer_night": False, 
            "fixed": {"연가": [], "특별": [], "교육": [], "휴일": []},
            "desired": {"주간": [], "야간": []}
        })

    cols = st.columns([2, 1, 1, 4, 1])
    cols[0].markdown("**이름**")
    cols[1].markdown("**주간선호**")
    cols[2].markdown("**야간선호**")
    cols[3].markdown("**근무 일정 세부설정 (고정/희망)**")
    cols[4].markdown("**삭제**")

    for idx, emp in enumerate(st.session_state.employees):
        c1, c2, c3, c4, c5 = st.columns([2, 1, 1, 4, 1])
        emp['name'] = c1.text_input(f"이름 {idx}", value=emp['name'], label_visibility="collapsed", placeholder="이름 입력")
        emp['prefer_day'] = c2.checkbox(f"주 {idx}", value=emp['prefer_day'], label_visibility="collapsed")
        emp['prefer_night'] = c3.checkbox(f"야 {idx}", value=emp['prefer_night'], label_visibility="collapsed")
        
        if 'fixed' not in emp or isinstance(emp['fixed'], str):
            emp['fixed'] = {"연가": [], "특별": [], "교육": [], "휴일": []}
        if 'desired' not in emp or isinstance(emp['desired'], str):
            emp['desired'] = {"주간": [], "야간": []}
            
        total_fixed = sum(len(v) for v in emp['fixed'].values())
        total_desired = sum(len(v) for v in emp['desired'].values())
        
        btn_label = f"📅 일정 관리 (고정 {total_fixed} / 희망 {total_desired})"
        
        with c4.popover(btn_label, use_container_width=True):
            st.markdown(f"**{emp['name'] if emp['name'] else '이름 없음'}** 요원 고정 일정 (필수)")
            valid_hol = [d for d in emp['fixed']['휴일'] if d in month_days]
            valid_ann = [d for d in emp['fixed']['연가'] if d in month_days]
            valid_spe = [d for d in emp['fixed']['특별'] if d in month_days]
            valid_edu = [d for d in emp['fixed']['교육'] if d in month_days]
            
            emp['fixed']['휴일'] = st.multiselect("🔴 지정 휴일", options=month_days, default=valid_hol, key=f"hol_{idx}")
            emp['fixed']['연가'] = st.multiselect("🌴 연가", options=month_days, default=valid_ann, key=f"ann_{idx}")
            emp['fixed']['특별'] = st.multiselect("🎁 특별휴가", options=month_days, default=valid_spe, key=f"spe_{idx}")
            emp['fixed']['교육'] = st.multiselect("📚 교육", options=month_days, default=valid_edu, key=f"edu_{idx}")

            st.divider()
            st.markdown("**💡 희망 근무 (가능한 경우 우선 배정)**")
            valid_des_day = [d for d in emp['desired']['주간'] if d in month_days]
            valid_des_night = [d for d in emp['desired']['야간'] if d in month_days]
            emp['desired']['주간'] = st.multiselect("☀️ 희망 주간", options=month_days, default=valid_des_day, key=f"des_d_{idx}")
            emp['desired']['야간'] = st.multiselect("🌙 희망 야간", options=month_days, default=valid_des_night, key=f"des_n_{idx}")

        if c5.button("🗑️", key=f"del_{idx}"):
            st.session_state.employees.pop(idx)
            st.rerun()

    st.header("📋 이월 데이터 (전달 마지막 4일)")
    carryover = {}
    preset_carryover_for_json = {}
    
    if st.session_state.employees:
        for emp in st.session_state.employees:
            if emp['name'].strip():
                st.subheader(f"📍 {emp['name']}")
                r_cols = st.columns(4)
                carryover[emp['name']] = {}
                preset_carryover_for_json[emp['name']] = {}
                
                for i, d in enumerate([-3, -2, -1, 0]):
                    default_val = st.session_state.preset_carryover.get(emp['name'], {}).get(str(d), "휴")
                    try:
                        default_idx = ["주", "야", "비", "휴"].index(default_val)
                    except ValueError:
                        default_idx = 3

                    val = r_cols[i].selectbox(f"{d}일 근무", ["주", "야", "비", "휴"], index=default_idx, key=f"carry_{emp['name']}_{d}")
                    
                    carryover[emp['name']][d] = SHIFT_MAP[val]
                    preset_carryover_for_json[emp['name']][str(d)] = val
                    
        st.session_state.carryover_data = carryover

    with st.sidebar:
        st.markdown("---")
        preset_data = {
            "employees": st.session_state.employees,
            "carryover": preset_carryover_for_json
        }
        json_str = json.dumps(preset_data, ensure_ascii=False, indent=2)
        st.download_button(
            label="📥 현재 입력 내용 백업하기",
            data=json_str,
            file_name=f"근무설정_백업.json",
            mime="application/json",
            use_container_width=True
        )

    st.divider()
    
    if st.button("🚀 근무표 생성하기", type="primary", use_container_width=True):
        if not st.session_state.employees:
            st.error("사회복무요원을 최소 한 명 이상 추가해 주세요.")
        else:
            is_success = run_scheduling_engine()
            if not is_success:
                st.error("🚨 지정하신 조건으로는 교대근무 제약(야간 후 휴무, 최대 연속 출근 등)을 맞출 수 없습니다!\n\n특정 날짜에 연가나 고정 휴일이 겹치지 않았는지 일정을 확인하고 다시 생성해 보세요.")
            else:
                st.rerun()

    if st.session_state.generated_results:
        st.markdown("### 📊 생성된 근무표 확인하기")
        btn_cols = st.columns(len(st.session_state.generated_results))
        for idx, res in enumerate(st.session_state.generated_results):
            if btn_cols[idx].button(f"🔍 {res.solution_label}안 상세 보기\n(점수: {res.score})", use_container_width=True):
                st.session_state.selected_idx = idx
                st.session_state.page = 'detail'
                st.rerun()

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
        
        desired_list = []
        for d in e['desired']['주간']: desired_list.append(FixedSchedule(d, ShiftType.DAY))
        for d in e['desired']['야간']: desired_list.append(FixedSchedule(d, ShiftType.NIGHT))
        
        final_emps.append(Employee(e['name'], e['prefer_day'], e['prefer_night'], fixed_list, desired_list))
    
    with st.spinner("최적의 근무표를 계산 중입니다... (최대 설정 시간만큼 소요될 수 있습니다)"):
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
    
    # 💡 [버그 수정] 사이드바 설정값이 아니라 '생성된 결과 원본'의 연, 월, 일수를 무조건 따르도록 고정
    year = res.year
    month = res.month
    num_days = res.num_days
    month_days = list(range(1, num_days + 1))

    c1, c2 = st.columns([1, 4])
    if c1.button("◀ 이전 설정으로 돌아가기"):
        st.session_state.page = 'main'
        st.rerun()
    c2.title(f"🗓️ {year}년 {month}월 근무표 [{res.solution_label}안]")

    ctrl1, ctrl2, _ = st.columns(3)
    show_details = ctrl1.toggle("📊 자세히 보기 (통계 및 합계 표시)", value=False)
    edit_mode = ctrl2.toggle("✏️ 수동 수정 모드", value=False)
    
    st.info("💡 수정 모드를 켜면 표를 직접 수정할 수 있습니다. 마음에 드는 대안을 찾으셨다면 하단의 '다음 달 설정 파일 저장'을 눌러 프리셋을 챙겨가세요.")

    table_data = []
    
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
            
    if show_details:
        for col in ["주간", "야간", "비번", "휴일", "연가", "특별", "교육", "합계"]:
            day_row[col] = None
    table_data.append(day_row)
    
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
        if show_details:
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

    st.markdown("---")
    st.markdown("### 🔍 요원별 인물 상세 정보 (달력 보기)")
    st.caption("아래 요원의 이름을 클릭하면 해당 요원의 한 달 스케줄 달력과 상세 설정을 편집할 수 있는 화면으로 이동합니다.")
    
    emp_names = [emp.name for emp in res.employees]
    if emp_names:
        cols_per_row = max(1, (len(emp_names) + 1) // 2)
        btn_cols = st.columns(cols_per_row)
        for idx, name in enumerate(emp_names):
            col_target = btn_cols[idx % cols_per_row]
            if col_target.button(f"👤 {name}", use_container_width=True, key=f"jump_{name}"):
                st.session_state.selected_emp_name = name
                st.session_state.page = 'individual'
                st.rerun()

    st.divider()
    dl_c1, dl_c2 = st.columns(2)
    
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        df.reset_index().to_excel(writer, index=False, sheet_name=f"{res.solution_label}안")
    dl_c1.download_button(
        label="📥 확정 근무표 엑셀(Excel) 다운로드", data=buffer.getvalue(),
        file_name=f"근무표_{year}년_{month}월_{res.solution_label}안.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )

    next_month_carryover = {}
    next_month_employees = []
    
    for emp in res.employees:
        next_month_carryover[emp.name] = {
            "-3": REVERSE_SHIFT_MAP.get(res.get_shift(emp.name, num_days - 3), "휴"),
            "-2": REVERSE_SHIFT_MAP.get(res.get_shift(emp.name, num_days - 2), "휴"),
            "-1": REVERSE_SHIFT_MAP.get(res.get_shift(emp.name, num_days - 1), "휴"),
            "0": REVERSE_SHIFT_MAP.get(res.get_shift(emp.name, num_days), "휴")
        }
        
        next_month_employees.append({
            "name": emp.name,
            "prefer_day": emp.prefer_day,
            "prefer_night": emp.prefer_night,
            "fixed": {"연가": [], "특별": [], "교육": [], "휴일": []},
            "desired": {"주간": [], "야간": []}
        })
        
    next_month_preset = {
        "employees": next_month_employees,
        "carryover": next_month_carryover
    }
    next_json_str = json.dumps(next_month_preset, ensure_ascii=False, indent=2)
    
    next_m = month + 1 if month < 12 else 1
    next_y = year if month < 12 else year + 1
    
    dl_c2.download_button(
        label=f"💾 다음 달({next_m}월) 세팅용 프리셋 파일 저장",
        data=next_json_str,
        file_name=f"근무설정_익월용_{next_y}년_{next_m}월.json",
        mime="application/json",
        type="primary",
        use_container_width=True
    )

# ==========================================
# 📺 화면 3: <인물별 정보> (개인 상세 뷰어 및 달력)
# ==========================================
def render_individual_page():
    res = st.session_state.generated_results[st.session_state.selected_idx]
    
    # 💡 [버그 수정] 개인 달력도 사이드바 설정값이 아니라 원본을 무조건 따르도록 고정
    year = res.year
    month = res.month
    num_days = res.num_days
    month_days = list(range(1, num_days + 1))
    
    emp_name = st.session_state.selected_emp_name

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

    st.markdown("### ⚙️ 개인 근무 제약 및 선호도 수정")
    exp1 = st.expander("🛠️ 이 요원의 선호도 및 고정/희망 일정 변경하기 (클릭하여 열기)", expanded=False)
    with exp1:
        cc1, cc2 = st.columns(2)
        emp_data['prefer_day'] = cc1.checkbox("주간 근무 선호", value=emp_data['prefer_day'], key=f"ind_pref_d")
        emp_data['prefer_night'] = cc2.checkbox("야간 근무 선호", value=emp_data['prefer_night'], key=f"ind_pref_n")
        
        st.markdown("**고정 일정 관리 (필수)**")
        emp_data['fixed']['휴일'] = st.multiselect("🔴 지정 휴일 선택", options=month_days, default=emp_data['fixed'].get('휴일', []), key="ind_hol")
        emp_data['fixed']['연가'] = st.multiselect("🌴 연가 선택", options=month_days, default=emp_data['fixed'].get('연가', []), key="ind_ann")
        emp_data['fixed']['특별'] = st.multiselect("🎁 특별휴가 선택", options=month_days, default=emp_data['fixed'].get('특별', []), key="ind_spe")
        emp_data['fixed']['교육'] = st.multiselect("📚 교육 선택", options=month_days, default=emp_data['fixed'].get('교육', []), key="ind_edu")
        
        st.divider()
        st.markdown("**💡 희망 근무 (가능한 경우 우선 배정)**")
        emp_data['desired']['주간'] = st.multiselect("☀️ 희망 주간", options=month_days, default=emp_data['desired'].get('주간', []), key="ind_des_d")
        emp_data['desired']['야간'] = st.multiselect("🌙 희망 야간", options=month_days, default=emp_data['desired'].get('야간', []), key="ind_des_n")
        
        action_c1, action_c2 = st.columns(2)
        if action_c1.button("💾 변경사항 적용 (저장)", type="primary", use_container_width=True):
            st.success(f"💾 {emp_name} 요원의 설정이 데이터베이스에 임시 반영되었습니다.")
            
        if action_c2.button("🔄 이 설정 바탕으로 근무표 전체 재생성 (리스케줄링)", use_container_width=True):
            is_success = run_scheduling_engine()
            if is_success:
                st.success("🎉 개인 최적화 변경사항을 반영하여 근무표가 완벽하게 리스케줄링(재생성) 되었습니다!")
                st.rerun()
            else:
                st.error("🚨 새로운 조건 제약이 너무 무거워 알고리즘 엔진이 해를 찾지 못했습니다. 일정을 약간 비워주시고 다시 시도해주세요.")

    st.markdown("---")
    st.markdown(f"### 🗓️ {month}월 스케줄 캘린더 구동 뷰어")

    try:
        import holidays
        kr_holidays = holidays.KR(years=year)
    except ImportError:
        kr_holidays = {}

    first_weekday, _ = calendar.monthrange(year, month)
    start_blank = (first_weekday + 1) % 7 

    cal_days = [None] * start_blank + month_days
    while len(cal_days) % 7 != 0:
        cal_days.append(None)

    headers = ["일", "월", "화", "수", "목", "금", "토"]
    h_cols = st.columns(7)
    for i, h in enumerate(headers):
        color = "#FF4B4B" if i == 0 else ("#0070C0" if i == 6 else "white")
        h_cols[i].markdown(f"<div style='text-align: center; background-color: #31333F; color: {color}; padding: 5px; font-weight: bold; border-radius: 4px;'>{h}</div>", unsafe_allow_html=True)

    for week_idx in range(len(cal_days) // 7):
        week_days = cal_days[week_idx*7 : (week_idx+1)*7]
        w_cols = st.columns(7)
        
        for day_pos, d in enumerate(week_days):
            if d is None:
                w_cols[day_pos].markdown("<div style='min-height: 80px;'></div>", unsafe_allow_html=True)
            else:
                date_obj = datetime.date(year, month, d)
                shift_val = res.get_shift(emp_name, d)
                shift_str = shift_val.value if shift_val else ""
                
                is_holiday = (day_pos == 0) or (date_obj in kr_holidays)
                is_saturday = (day_pos == 6)
                day_color = "#FF4B4B" if is_holiday else ("#0070C0" if is_saturday else "white")
                
                cell_style = CAL_COLOR_MAP.get(shift_str, "background-color: #262730; color: white;")
                
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
                w_cols[day_pos].markdown(html_box, unsafe_allow_html=True)

if st.session_state.page == 'main':
    render_main_page()
elif st.session_state.page == 'detail':
    render_detail_page()
elif st.session_state.page == 'individual':
    render_individual_page()
