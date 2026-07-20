"""
report_agent.py — Weekly analytics report için kısa AI yorumu üretir.

ÖNEMLİ: Bu agent HİÇBİR SAYI HESAPLAMAZ. Tüm rakamlar zaten
tools/generate_weekly_report.py tarafından SQL/Python ile hesaplanmış
olarak gelir. Model sadece bu hazır rakamlara bakıp 2-3 cümlelik
insan-okunur bir yorum yazar (öne çıkanlar, dikkat edilmesi gerekenler).

Neden ayrı, basit bir çağrı (ReAct loop değil):
  Ana pricing agent (bedrock_agent.py) fiyat KARARI alıyor, çok adımlı
  muhakeme gerektiriyor. Bu agent sadece VAR OLAN veriyi özetliyor —
  tool çağırmasına gerek yok, tek seferlik bir "yorumla" isteği yeterli.
"""

import os

import boto3
from dotenv import load_dotenv

load_dotenv()

AWS_REGION = os.getenv("AWS_REGION", "eu-central-1")
MODEL_ID   = os.getenv("BEDROCK_MODEL_ID", "eu.amazon.nova-lite-v1:0")

_bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)

_SYSTEM_PROMPT = """You are a data analyst summarizing a weekly e-commerce pricing report.
You will be given pre-computed statistics — numbers are already correct, DO NOT recalculate
or invent any numbers. Your only job is to write a short, plain-English insight (2-4 sentences)
that a business manager would find useful: what stood out, what might need attention.
Do not repeat every number — pick the 1-2 most relevant points. Do not use markdown formatting."""


def generate_report_insight(stats_summary: str) -> str:
    """
    Verilen hazır istatistik özetinden 2-4 cümlelik insan-okunur yorum üretir.

    Args:
        stats_summary: generate_weekly_report()'ın döndürdüğü düz metin özet

    Returns:
        str — kısa yorum metni. Bedrock hatası olursa boş string döner
        (rapor yine de sayılarla birlikte gönderilir, yorum opsiyonel).
    """
    try:
        response = _bedrock.converse(
            modelId=MODEL_ID,
            system=[{"text": _SYSTEM_PROMPT}],
            messages=[
                {
                    "role": "user",
                    "content": [{"text": f"Weekly stats:\n{stats_summary}\n\nWrite the insight now."}],
                }
            ],
            inferenceConfig={"maxTokens": 300, "temperature": 0.3},
        )
        for block in response["output"]["message"]["content"]:
            if "text" in block:
                return block["text"].strip()
        return ""
    except Exception as e:
        print(f"[report_agent] Insight generation failed (non-fatal): {e}")
        return ""


if __name__ == "__main__":
    from tools.generate_weekly_report import generate_weekly_report

    report = generate_weekly_report(days=7)
    insight = generate_report_insight(report["stats_summary"])
    print("STATS:", report["stats_summary"])
    print("\nINSIGHT:", insight)
