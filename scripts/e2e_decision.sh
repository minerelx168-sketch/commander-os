#!/bin/bash
# Live: record a decision from consult #5 and score it
set -e
H=http://localhost:8100
curl -s -X POST "$H/api/decisions" -H 'Content-Type: application/json' \
  -d '{"consult_id":5,"question":"มีคนเสนอซื้อกิจการตู้กดดอกไม้ 2 ล้านบาท ขายหรือทำต่อ?","decision":"ขอดูงบ 12 เดือนก่อนตาม CFO แล้วค่อยต่อรอง"}' | head -c 200
echo
curl -s -X POST "$H/api/decisions/1/score" -H 'Content-Type: application/json' \
  -d '{"outcome":"พบต้นทุนซ่อนจริง ราคาที่เหมาะคือ 2.6 ล้าน ต่อรองได้เพิ่ม","verdict":"saved"}' | head -c 200
echo
curl -s "$H/api/decisions" | python3 -c "import json,sys; j=json.load(sys.stdin); print('stats:', j['stats'])"
