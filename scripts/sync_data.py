import requests
import sqlite3
import os
from dotenv import load_dotenv

# >> 실행 및 확인
# Cursor 터미널에서 아래 명령어를 쳐서 실제로 데이터를 가져오는지 확인
# python scripts/sync_data.py
# 성공했다면 폴더에 bank_data.db 파일 생성

# .env 파일에서 환경변수 로드
load_dotenv()

API_KEY = os.getenv("FINLIFE_API_KEY")
BASE_URL = "http://finlife.fss.or.kr/finlifeapi/savingProductsSearch.json"
DB_PATH = "bank_data.db"

def fetch_and_save_data():
    # 공식 가이드에 따른 파라미터
    params = {
        'auth': API_KEY,
        'topFinGrpNo': '020000',  # 권역 코드 (020000: 은행)
        'pageNo': '1'
    }
    
    try:
        response = requests.get(BASE_URL, params=params)
        response.raise_for_status()
        data = response.json()
        
        # 에러 코드 확인 (정상이면 "000")
        err_cd = data.get('result', {}).get('err_cd')
        if err_cd != "000":
            print(f"❌ API 에러 발생 (코드 {err_cd}): {data.get('result', {}).get('err_msg')}")
            return
            
    except Exception as e:
        print(f"❌ 요청 중 오류 발생: {e}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 테이블 생성 (기존 테이블 삭제 후 재생성하여 구조 동기화)
    cursor.execute('DROP TABLE IF EXISTS savings')
    cursor.execute('''
    CREATE TABLE savings (
        id TEXT PRIMARY KEY,
        bank_name TEXT,
        product_name TEXT,
        special_condition TEXT,
        intr_rate_type_nm TEXT,
        base_rate REAL,
        max_rate REAL,
        term INTEGER
    )
    ''')

    base_list = data.get('result', {}).get('baseList', [])
    option_list = data.get('result', {}).get('optionList', [])

    count = 0
    for base in base_list:
        # 해당 상품의 12개월 옵션 필터링
        relevant_options = [
            opt for opt in option_list 
            if opt['fin_prdt_cd'] == base['fin_prdt_cd'] and str(opt['save_trm']) == "12"
        ]
        
        if not relevant_options:
            continue
            
        # 단리(S) 우선 선택, 없으면 첫 번째 옵션
        selected_opt = next((o for o in relevant_options if o['intr_rate_type'] == 'S'), relevant_options[0])
        
        # 금리 데이터 추출 (null 처리)
        base_rate = selected_opt.get('intr_rate') if selected_opt.get('intr_rate') is not None else 0.0
        max_rate = selected_opt.get('intr_rate2') if selected_opt.get('intr_rate2') is not None else base_rate

        cursor.execute('''
        INSERT INTO savings VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            base['fin_prdt_cd'],
            base['kor_co_nm'],
            base['fin_prdt_nm'],
            base['spcl_cnd'],
            selected_opt['intr_rate_type_nm'],
            base_rate,
            max_rate,
            int(selected_opt['save_trm'])
        ))
        count += 1

    conn.commit()
    conn.close()
    print(f"✅ 동기화 완료: 총 {count}개의 은행권 적금(12개월) 상품 저장됨.")

if __name__ == "__main__":
    fetch_and_save_data()