import streamlit as st
import datetime
import calendar
import pandas as pd
import io
from models import Employee, FixedSchedule, ShiftType
from scheduler import ShiftScheduler
from validator import validate

st.set_page_config(page_title="사회복무요원 근무표 생성기", layout="wide")

st.title("🚀 사회복무요원 근무표 자동화 시스템")

# 1. 사이드바: 기본 설정
with st.sidebar:
    st.header("⚙️ 기본 설정")
    today = datetime.date.today()
    st.markdown("**생성 연/월 선택**")
    y_col, m_col = st.columns(2)
    year = y_col.selectbox("연도", range(today.year - 1, today.year + 4), index=1, label_visibility="collapsed", format_func=lambda x: f"{x}년")
    month = m_col.selectbox("월", range(1, 13), index=today.month - 1, label_visibility="collapsed", format_func=lambda x: f"{x}월")
    
    num_solutions = st.slider("생성할 대안 수", 1, 5, 3)
    time_limit = st.number_input("탐색 시간 제한(초)", 10, 300, 30)

# 해당 월의 총 일수 계산
_, num_days = calendar.monthrange(year, month)
month_days = list(range(1, num_days + 1))

# 2. 메인: 사회복무요원 관리
st.header("👥 사회복무요원 관리")

if 'employees' not in st.session_state:
    st.session_state.employees = []

def add_employee():
    st.session_state.employees.append({
        "name": "", 
        "prefer_day": True, 
        "prefer_night": False, 
        "fixed": {"연가": [], "특별": [], "교육": [], "휴일": []}
    })

if st.button("➕ 사회복무요원 추가"):
    add_employee()

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
    
    # 캐시 충돌 방지 및 안전장치
    old_fixed = emp.get('fixed', {})
    if isinstance(old_fixed, str):
        emp['fixed'] = {"연가": [], "특별": [], "교육": [], "휴일": []}
    else:
        emp['fixed'] = {
            "연가": old_fixed.get("연가", []), 
            "특별": old_fixed.get("특별", []), 
            "교육": old_fixed.get("교육", []), 
            "휴일": old_fixed.get("휴일", [])
        }
        
    total_fixed = len(emp['fixed']['연가']) + len(emp['fixed']['특별']) + len(emp['fixed']['교육']) + len(emp['fixed']['휴일'])
    btn_label = f"📅 일정 관리 (총 {total_fixed}일)" if total_fixed > 0 else "📅 일정 추가"
    
    with c4.popover(btn_label, use_container_width=True):
        st.markdown(f"**{emp['name'] if emp['name'] else '이름 없음'}** 요원의 {month}월 고정 일정")
        
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

# 3. 이월 데이터 입력
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
                mapping = {"주간": ShiftType.DAY, "야간": ShiftType.NIGHT, "비번": ShiftType.OFF, "휴일": ShiftType.HOLIDAY}
                carryover[emp['name']][d] = mapping[val]

# 4. 근무표 생성 실행 및 결과 시각화
st.divider()
if st.button("🚀 근무표 만들기", type="primary", use_container_width=True):
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
        
        with st.spinner("최적의 근무표를 계산 중입니다... (잠시만 기다려주세요)"):
            scheduler = ShiftScheduler(year, month, final_emps, carryover, num_solutions, time_limit)
            results = scheduler.solve()
            
            if not results:
                st.error("조건에 맞는 해를 찾지 못했습니다. 제약(인원 수, 고정 일정 등)을 완화해 보세요.")
            else:
                st.success("🎉 근무표 생성이 완료되었습니다! 아래 탭에서 대안을 확인하세요.")
                
                tabs = st.tabs([f"{res.solution_label}안 (점수: {res.score})" for res in results])
                
                for idx, res in enumerate(results):
                    with tabs[idx]:
                        table_data = []
                        for emp in res.employees:
                            row = {"이름": emp.name}
                            
                            # 개인별 일일 근무 데이터
                            for d in month_days:
                                shift = res.get_shift(emp.name, d)
                                row[f"{d}일"] = shift.value if shift else None # 엑셀 빈칸용 None
                                
                            # 요원별 통계 컬럼
                            stats = res.get_stats(emp.name)
                            row["주간"] = stats['주간']
                            row["야간"] = stats['야간']
                            row["비번"] = stats['비번']
                            row["휴일"] = stats['휴일']
                            row["연가"] = stats['연가']
                            row["특별"] = stats['특별']
                            row["교육"] = stats['교육']
                            row["합계"] = (stats['주간'] + stats['야간'] + stats['비번'] + 
                                         stats['휴일'] + stats['연가'] + stats['특별'] + stats['교육'])
                            table_data.append(row)
                            
                        # 하단 일일 인원 합계 계산
                        day_count_row = {"이름": "주간 근무인원"}
                        night_count_row = {"이름": "야간 근무인원"}
                        
                        for d in month_days:
                            day_count = sum(1 for emp in res.employees if res.get_shift(emp.name, d) == ShiftType.DAY)
                            night_count = sum(1 for emp in res.employees if res.get_shift(emp.name, d) == ShiftType.NIGHT)
                            # 💡 엑셀 수식 계산을 위해 순수 숫자로 입력
                            day_count_row[f"{d}일"] = day_count
                            night_count_row[f"{d}일"] = night_count
                            
                        # 합계 행의 통계 빈칸 처리
                        for col in ["주간", "야간", "비번", "휴일", "연가", "특별", "교육", "합계"]:
                            day_count_row[col] = None
                            night_count_row[col] = None
                            
                        table_data.append(day_count_row)
                        table_data.append(night_count_row)
                            
                        # 데이터프레임 생성 (원본 데이터는 엑셀 다운로드용으로 보존)
                        df = pd.DataFrame(table_data)
                        
                        # 💡 핵심 해결: 웹 화면 출력용으로만 글자로 변환하고 None을 완벽한 빈칸("")으로 교체
                        df_display = df.astype(str).replace(["None", "nan", "<NA>"], "")
                        st.dataframe(df_display, use_container_width=True, hide_index=True)
                        
                        # 엑셀 다운로드 (원본 df 사용: 숫자는 숫자대로, None은 빈칸으로 정상 저장됨)
                        buffer = io.BytesIO()
                        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                            df.to_excel(writer, index=False, sheet_name=f"{res.solution_label}안")
                        
                        st.download_button(
                            label=f"📥 {res.solution_label}안 엑셀(Excel) 다운로드",
                            data=buffer.getvalue(),
                            file_name=f"근무표_{year}년_{month}월_{res.solution_label}안.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            key=f"download_{idx}"
                        )
