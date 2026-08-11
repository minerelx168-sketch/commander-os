#!/bin/bash
# End-to-end: run a real board (web research on), then pull every artefact from
# the live agents and inspect what actually came back.
set -u
PY=/Users/boston/.hermes/hermes-agent/venv/bin/python
H=http://localhost:8100
Q='ควรเปิดบริการส่งดอกไม้แบบสมัครสมาชิกรายเดือนสำหรับออฟฟิศในกรุงเทพไหม'

echo "=== create consult (web research ON) ==="
curl -s -m120 -X POST "$H/api/consult" -H 'Content-Type: application/json' \
  -d "{\"question\":\"$Q\",\"web_research\":true}" -o /tmp/d0.json -w 'HTTP %{http_code}\n'
SID=$($PY -c "import json;print(json.load(open('/tmp/d0.json'))['id'])")
echo "sid=$SID"; echo "$SID" > /tmp/sid_final

for i in 1 2 3 4 5; do
  curl -s -m290 -X POST "$H/api/consult/$SID/advance" -H 'Content-Type: application/json' \
    -d '{}' -o "/tmp/d$i.json" -w "round$i HTTP %{http_code} "
  $PY -c "
import json;d=json.load(open('/tmp/d$i.json'))
s=(d.get('steps') or [])[-1] if d.get('steps') else {}
r=s.get('results') or {}
oks=sum(1 for v in r.values() if v.get('ok'))
print(f\"{s.get('key','?'):11} advisors_ok={oks}/{len(r)} status={d.get('status')} next={d.get('next_step')}\")"
done

echo
echo "=== pull every departmental artefact from the live agents ==="
for dept in researcher cmo coo datalyst; do
  printf "%-11s " "$dept"
  code=$(curl -s -m400 "$H/api/consult/$SID/deliverable/$dept.pdf" -o "/tmp/dl_$dept.pdf" -w '%{http_code}')
  size=$(wc -c < "/tmp/dl_$dept.pdf" | tr -d ' ')
  if [ "$code" = "200" ]; then
    echo "HTTP $code  ${size}B  $(head -c 4 "/tmp/dl_$dept.pdf")"
  else
    echo "HTTP $code  ->  $(head -c 220 "/tmp/dl_$dept.pdf")"
  fi
done
printf "%-11s " "cfo(xlsx)"
code=$(curl -s -m400 "$H/api/consult/$SID/financial-model.xlsx" -o /tmp/dl_cfo.xlsx -w '%{http_code}')
echo "HTTP $code  $(wc -c < /tmp/dl_cfo.xlsx | tr -d ' ')B"
