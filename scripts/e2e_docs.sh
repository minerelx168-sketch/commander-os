#!/bin/bash
# Live E2E: simulate a LINE webhook message -> doc saved -> knowledge feeds the board
set -e
H=http://localhost:8100
sleep 3
echo "== simulate LINE text message =="
curl -s -X POST "$H/api/line/webhook" -H 'Content-Type: application/json' \
  -d '{"events":[{"type":"message","message":{"type":"text","text":"บันทึกธุรกิจ: ตู้กดดอกไม้เอกมัยมี 2 ตู้ ยอดขายเฉลี่ยวันละ 4,500 บาท ต้นทุนดอกไม้ 40% ค่าเช่าแบ่ง GP 10%"}}]}'
echo
echo "== docs state =="
curl -s "$H/api/docs" | python3 -c "
import json, sys
j = json.load(sys.stdin)
print('docs:', len(j['documents']), '| drive:', j['drive_connected'], '| line:', j['line_connected'], '| knowledge:', j['knowledge_chars'], 'chars')
d = j['documents'][0]
print('latest:', d['name'], '| src:', d['source'], '| loc:', d['location'])
"
