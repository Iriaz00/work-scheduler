import streamlit as st
import datetime
import pandas as pd
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

# 2. 메인: 사회복무요원 관리
st.header("👥 사회복무요원 관리")

if 'employees' not in st.session_state:
    st.session_state.employees = []

def add_employee():
    # 요청사항 반영: 이름은 빈칸으로 초기화
    st.session_state.employees.append({"name": "", "prefer_day": True, "prefer_night": False, "fixed": ""})

if st.button("➕ 사회복무요원 추가"):
    add_employee()

emp_data = []
cols = st.columns([2, 1, 1, 4, 1])
cols[0].markdown("**이름**")
cols[1].markdown("**주간선호**")
cols[2].markdown("**야간선호**")
cols[3].markdown("**고정 일정 (예: 5:연가, 15:교육)**")
cols[4].markdown("**삭제**")

for idx, emp in enumerate(st.session_state.employees):
    c1, c2, c3, c4, c5 = st.columns([2, 1, 1, 4, 1])
    emp['name'] = c1.text_input(f"이름 {idx}", value=emp['name'], label_visibility="collapsed", placeholder="이름 입력")
    emp['prefer_day'] = c2.checkbox(f"주 {idx}", value=emp['prefer_day'], label_visibility="collapsed")
    emp['prefer_night'] = c3.checkbox(f"야 {idx}", value=emp['prefer_night'], label_visibility="collapsed")
    emp['fixed'] = c4.text_input(f"일정 {idx}", value=emp['fixed'], label_visibility="collapsed", placeholder="날짜:항목 (쉼표 구분)")
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

# 4. 근무표 생성 실행
if st.button("🚀 근무표 만들기", type="primary", use_container_width=True):
    if not st.session_state.employees:
        st.error("사회복무요원을 최소 한 명 이상 추가해 주세요.")
    else:
        # 데이터 변환
        final_emps = []
        for e in st.session_state.employees:
            fixed_list = []
            if e['fixed'].strip():
                for item in e['fixed'].split(','):
                    try:
                        d_str, s_str = item.split(':')
                        d_idx = int(d_str.strip())
                        s_map = {"연가": ShiftType.ANNUAL, "특별": ShiftType.SPECIAL, "교육": ShiftType.EDUCATION}
                        fixed_list.append(FixedSchedule(d_idx, s_map.get(s_str.strip(), ShiftType.HOLIDAY)))
                    except: pass
            final_emps.append(Employee(e['name'], e['prefer_day'], e['prefer_night'], fixed_list))
        
        # 스케줄링 실행
        with st.spinner("최적의 근무표를 계산 중입니다..."):
            scheduler = ShiftScheduler(year, month, final_emps, carryover, num_solutions, time_limit)
            results = scheduler.solve()
            
            if not results:
                st.error("조건에 맞는 해를 찾지 못했습니다. 제약을 완화해 보세요.")
            else:
                for res in results:
                    st.success(f"[{res.solution_label}안] 생성 완료! (점수: {res.score})")
                    # 결과 데이터프레임 시각화 로직 추가...
                    # (이후 표 출력 및 엑셀 다운로드 기능 배치)
