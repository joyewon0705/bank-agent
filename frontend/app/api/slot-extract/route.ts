import { NextRequest, NextResponse } from "next/server";

type YesNoUnknown = "yes" | "no" | "unknown";

type InputJSON = {
  product_type: string;
  last_questions: string[];
  user_message: string;
};

type OutputJSON = {
  slots: {
    monthly_amount?: number;
    term_months?: number;
    lump_sum?: number;
    income_monthly?: number;
    desired_amount?: number;
  };
  eligibility: {
    salary_transfer: YesNoUnknown;
    auto_transfer: YesNoUnknown;
    card_spend: YesNoUnknown;
    primary_bank: YesNoUnknown;
    non_face: YesNoUnknown;
    youth: YesNoUnknown;
  };
  meta: {
    user_uncertain: boolean;
  };
};

function baseOutput(): OutputJSON {
  return {
    slots: {},
    eligibility: {
      salary_transfer: "unknown",
      auto_transfer: "unknown",
      card_spend: "unknown",
      primary_bank: "unknown",
      non_face: "unknown",
      youth: "unknown",
    },
    meta: { user_uncertain: false },
  };
}

// 아주 러프한 숫자 파싱(만원/천만원/억원 등)
function parseKoreanMoney(text: string): number | undefined {
  const t = text.replace(/,/g, "").trim();

  // 3천만원 / 2000만원 / 5억 / 1.5억 / 50만
  const m = t.match(/(\d+(\.\d+)?)(\s*)?(억|천만원|백만원|만원|만|원)/);
  if (!m) return undefined;

  const val = Number(m[1]);
  const unit = m[4];

  if (Number.isNaN(val)) return undefined;

  if (unit === "억") return Math.round(val * 100_000_000);
  if (unit === "천만원") return Math.round(val * 10_000_000);
  if (unit === "백만원") return Math.round(val * 1_000_000);
  if (unit === "만원" || unit === "만") return Math.round(val * 10_000);
  if (unit === "원") return Math.round(val);

  return undefined;
}

function parseMonths(text: string): number | undefined {
  const m = text.match(/(\d+)\s*(개월|달|month|months)/i);
  if (!m) return undefined;
  const n = Number(m[1]);
  return Number.isFinite(n) ? n : undefined;
}

function detectYesNoUnknown(text: string, yesWords: RegExp, noWords: RegExp): YesNoUnknown {
  if (yesWords.test(text)) return "yes";
  if (noWords.test(text)) return "no";
  return "unknown";
}

function ruleBasedExtract(input: InputJSON): OutputJSON {
  const out = baseOutput();
  const msg = (input.user_message || "").trim();

  // 확신 낮음 신호(대충/잘 모르겠/아마/가능할지도 등)
  out.meta.user_uncertain = /(잘\s*모르|대충|아마|그냥|가능할?지|모르겠|애매)/.test(msg);

  // 기간
  const months = parseMonths(msg);
  if (months) out.slots.term_months = months;

  // 금액
  const money = parseKoreanMoney(msg);
  // product type에 따라 어느 슬롯에 꽂을지
  if (money !== undefined) {
    if (/적금/.test(input.product_type)) {
      // "매달 50만원" 식이면 monthly_amount 우선
      if (/(매달|월|한달|매월)/.test(msg)) out.slots.monthly_amount = money;
      else out.slots.lump_sum = money;
    } else if (/예금/.test(input.product_type)) {
      out.slots.lump_sum = money;
    } else if (/대출/.test(input.product_type)) {
      // "희망 5천" "필요 5천" vs "월 소득 300"
      if (/(소득|월급|연봉)/.test(msg)) out.slots.income_monthly = money;
      else out.slots.desired_amount = money;
    } else {
      // 기본값
      out.slots.lump_sum = money;
    }
  }

  // eligibility 감지
  out.eligibility.salary_transfer = detectYesNoUnknown(msg, /(급여이체|월급\s*이체|급여\s*받)/, /(급여이체\s*불가|월급\s*안받|급여\s*없)/);
  out.eligibility.auto_transfer = detectYesNoUnknown(msg, /(자동이체|정기이체|오토이체)/, /(자동이체\s*싫|자동이체\s*불가|정기이체\s*안)/);
  out.eligibility.card_spend = detectYesNoUnknown(msg, /(카드\s*실적|카드\s*사용|월\s*카드)/, /(카드\s*안써|카드\s*싫|실적\s*못)/);
  out.eligibility.primary_bank = detectYesNoUnknown(msg, /(주거래|메인\s*은행|주로\s*쓰는\s*은행)/, /(주거래\s*없|메인\s*없)/);
  out.eligibility.non_face = detectYesNoUnknown(msg, /(비대면|모바일\s*가입|앱으로)/, /(대면|영업점|방문)/);
  out.eligibility.youth = detectYesNoUnknown(msg, /(청년|만\s*3[0-9]|20대|사회초년)/, /(청년\s*아님|40대|50대)/);

  return out;
}

/**
 * ✅ 여기서 LLM 붙이려면:
 * - input(JSON) => LLM 프롬프트로 전달
 * - LLM은 반드시 아래 OutputJSON 스키마로만 응답
 * - 실패 시 ruleBasedExtract로 fallback
 */
export async function POST(req: NextRequest) {
  const body = (await req.json()) as InputJSON;

  // 1) (현재) 규칙 기반으로 응답
  const extracted = ruleBasedExtract(body);

  // 2) (옵션) LLM 붙일 경우, 여기서 extracted 대신 모델 결과를 넣으면 됨.
  //    - 모델 결과가 JSON 파싱 실패/필드 누락이면 ruleBasedExtract fallback 권장.

  return NextResponse.json(extracted);
}
