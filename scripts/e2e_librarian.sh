#!/bin/bash
# Live E2E: librarian — create projects, send LINE doc, verify auto-filing with real Gemini
set -e
H=http://localhost:8100
sleep 3
echo "== create projects =="
curl -s -X POST "$H/api/docs/projects" -H 'Content-Type: application/json' -d '{"name":"YourFin"}' | head -c 120
echo
curl -s -X POST "$H/api/docs/projects" -H 'Content-Type: application/json' -d '{"name":"FlowerVending"}' | head -c 120
echo
echo "== send LINE doc: mobile installment table (should file into YourFin) =="
curl -s -X POST "$H/api/line/webhook" -H 'Content-Type: application/json' \
  -d '{"events":[{"type":"message","message":{"type":"text","text":"ตารางผ่อนมือถือ iPhone 17 ลูกค้าผ่อนงวดละ 1,250 บาท 24 งวด ดอกเบี้ย 1.2% ต่อเดือน"}}]}'
echo
echo "== send LINE doc: flower stock note (should file into FlowerVending) =="
curl -s -X POST "$H/api/line/webhook" -H 'Content-Type: application/json' \
  -d '{"events":[{"type":"message","message":{"type":"text","text":"สต็อกดอกกุหลาบตู้เอกมัย เหลือ 12 ช่อ เติมพรุ่งนี้ 30 ช่อ"}}]}'
echo
echo "== verify filing =="
curl -s "$H/api/docs" | python3 -c "
import json, sys
j = json.load(sys.stdin)
print('projects:', j['projects'])
for d in j['documents'][:2]:
    print(f\"doc #{d['id']}: {d['text'][:40]}... -> project: {d['project']}\")
"
