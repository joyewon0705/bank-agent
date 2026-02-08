import requests
import sqlite3
import os
import datetime
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("FINLIFE_API_KEY")
DB_PATH = "bank_data.db"

# 1. API 설정 리스트
API_CONFIGS = [
    {"key": "saving", "name": "적금", "url": "http://finlife.fss.or.kr/finlifeapi/savingProductsSearch.json"},
    {"key": "deposit", "name": "정기예금", "url": "http://finlife.fss.or.kr/finlifeapi/depositProductsSearch.json"},
    {"key": "annuity", "name": "연금저축", "url": "http://finlife.fss.or.kr/finlifeapi/annuitySavingProductsSearch.json"},
    {"key": "mortgage", "name": "주택담보대출", "url": "http://finlife.fss.or.kr/finlifeapi/mortgageLoanProductsSearch.json"},
    {"key": "rent", "name": "전세자금대출", "url": "http://finlife.fss.or.kr/finlifeapi/rentLoanProductsSearch.json"},
    {"key": "credit", "name": "개인신용대출", "url": "http://finlife.fss.or.kr/finlifeapi/creditLoanProductsSearch.json"}
]

def setup_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    # 공통 기본 정보 테이블
    cur.execute('''CREATE TABLE IF NOT EXISTS products_base (
        fin_prdt_cd TEXT PRIMARY KEY,
        product_type TEXT,
        kor_co_nm TEXT,
        fin_prdt_nm TEXT,
        join_way TEXT,
        spcl_cnd TEXT,
        last_updated TEXT
    )''')

    # 예/적금 상세 (Step 2.3 확장)
    cur.execute('''CREATE TABLE IF NOT EXISTS options_savings (
        fin_prdt_cd TEXT, save_trm INTEGER, intr_rate REAL, intr_rate2 REAL, intr_rate_type_nm TEXT
    )''')

    # 연금저축 상세 (Step 2.4 반영)
    cur.execute('''CREATE TABLE IF NOT EXISTS options_annuity (
        fin_prdt_cd TEXT, pnsn_kind_nm TEXT, prdt_type_nm TEXT, avg_prft_rate REAL, btrm_prft_rate_1 REAL
    )''')

    # 대출 상세 (주담대/전세)
    cur.execute('''CREATE TABLE IF NOT EXISTS options_loan (
        fin_prdt_cd TEXT, mrtg_typ_nm TEXT, rpay_alph_nm TEXT, lend_rate_typ_nm TEXT, lend_rate_min REAL, lend_rate_max REAL
    )''')

    conn.commit()
    return conn

def sync():
    conn = setup_db()
    cur = conn.cursor()
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    for config in API_CONFIGS:
        print(f"📡 {config['name']} 데이터 수집 중...")
        groups = ['020000', '030300'] if config['key'] in ['annuity', 'mortgage', 'rent', 'credit'] else ['020000']
        
        for group in groups:
            try:
                response = requests.get(
                    config['url'], 
                    params={'auth': API_KEY, 'topFinGrpNo': group, 'pageNo': '1'},
                    timeout=10 # 타임아웃 추가
                )
                
                # 1. 응답 코드가 200(정상)인지 확인
                if response.status_code != 200:
                    print(f"   ⚠️ {config['name']} ({group}) 서버 응답 오류: {response.status_code}")
                    continue

                # 2. JSON 파싱 시도 (여기서 에러가 나면 except로 빠짐)
                res = response.json()
                result = res.get('result', {})
                
                if result.get('err_cd') != "000":
                    print(f"   ⚠️ API 비즈니스 에러: {result.get('err_msg')}")
                    continue

                # --- 데이터 저장 로직 (기존과 동일) ---
                base_list = result.get('baseList', [])
                for base in base_list:
                    cur.execute('''INSERT INTO products_base VALUES (?,?,?,?,?,?,?) 
                                   ON CONFLICT(fin_prdt_cd) DO UPDATE SET last_updated=excluded.last_updated''',
                                (base['fin_prdt_cd'], config['key'], base['kor_co_nm'], base['fin_prdt_nm'], 
                                 base['join_way'], base.get('spcl_cnd', ''), now))

                opts = result.get('optionList', [])
                for opt in opts:
                    cd = opt['fin_prdt_cd']
                    if config['key'] in ['saving', 'deposit']:
                        cur.execute("INSERT INTO options_savings VALUES (?,?,?,?,?)", (cd, opt['save_trm'], opt['intr_rate'], opt['intr_rate2'], opt['intr_rate_type_nm']))
                    elif config['key'] in ['mortgage', 'rent']:
                        # 대출 상품별로 필드가 다를 수 있으니 get()으로 안전하게 가져옴
                        cur.execute("INSERT INTO options_loan VALUES (?,?,?,?,?,?)", 
                                    (cd, opt.get('mrtg_typ_nm'), opt.get('rpay_type_nm'), opt.get('lend_rate_type_nm'), opt.get('lend_rate_min'), opt.get('lend_rate_max')))
                
                print(f"   ✅ {config['name']} ({group}) 수집 완료")
                conn.commit() # 권역별로 저장 확정

            except requests.exceptions.JSONDecodeError:
                print(f"   ❌ {config['name']} ({group}) JSON 파싱 실패 (서버가 잘못된 형식을 반환함)")
            except Exception as e:
                print(f"   ❌ {config['name']} ({group}) 알 수 없는 에러: {e}")

    print("\n🏁 모든 데이터 수집 시도가 끝났습니다.")

if __name__ == "__main__":
    sync()