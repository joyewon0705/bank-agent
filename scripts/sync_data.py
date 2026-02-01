import requests
import sqlite3
import os
from dotenv import load_dotenv

# >> 실행 및 확인
# Cursor 터미널에서 아래 명령어를 쳐서 실제로 데이터를 가져오는지 확인하세요.
# python scripts/sync_data.py
# 성공했다면 폴더에 bank_data.db 파일이 생겼을 겁니다.

# .env 파일에서 환경변수 로드
load_dotenv()

API_KEY = os.getenv("FINLIFE_API_KEY")
BASE_URL = "http://finlife.fss.or.kr/금융상품대행/api/savingProductsSearch.json"
DB_PATH = "bank_data.db"

def fetch_and_save_data():
    params = {
        'auth': API_KEY,
        'topFinGrpNo': '020000',  # 은행권역
        'pageNo': '1'
    }
    
    response = requests.get(BASE_URL, params=params)
    if response.status_code != 200:
        print("API 호출 실패")
        return

    data = response.json()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 테이블 정의
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS savings (
        id TEXT PRIMARY KEY,
        bank_name TEXT,
        product_name TEXT,
        special_condition TEXT,
        base_rate REAL,
        max_rate REAL,
        term INTEGER
    )
    ''')

    base_list = data['result']['baseList']
    option_list = data['result']['optionList']

    for base in base_list:
        # 12개월 단리 상품만 필터링 (가장 대중적인 기준)
        options = [opt for opt in option_list if opt['fin_prdt_cd'] == base['fin_prdt_cd'] and opt['save_trm'] == "12"]
        
        if options:
            opt = options[0]
            cursor.execute('''
            INSERT OR REPLACE INTO savings VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                base['fin_prdt_cd'],     # 상품 코드
                base['kor_co_nm'],       # 은행명
                base['fin_prdt_nm'],     # 상품명
                base['spcl_cnd'],        # 우대 조건 텍스트
                opt['intr_rate'],        # 기본 금리
                opt['intr_rate2'],       # 최고 우대 금리
                int(opt['save_trm'])     # 저축 기간
            ))

    conn.commit()
    conn.close()
    print("✅ 데이터 수집 및 DB 저장 완료!")

if __name__ == "__main__":
    fetch_and_save_data()