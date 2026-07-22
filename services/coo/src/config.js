// การตั้งค่าส่วนกลางของระบบ COO Command
// อ่านจาก environment variables พร้อมค่า default ที่ปลอดภัย

const bool = (v, d = false) =>
  v === undefined ? d : ['1', 'true', 'yes', 'on'].includes(String(v).toLowerCase());

const int = (v, d) => {
  const n = parseInt(v, 10);
  return Number.isFinite(n) ? n : d;
};

export const config = {
  port: int(process.env.PORT, 8080),
  host: process.env.HOST || '0.0.0.0',

  llm: {
    provider: (process.env.LLM_PROVIDER || 'mock').toLowerCase(),
    apiUrl: process.env.MANUS_API_URL || 'https://api.manus.im/v1/chat/completions',
    apiKey: process.env.MANUS_API_KEY || '',
    model: process.env.MANUS_MODEL || 'manus-1',
    maxSteps: int(process.env.AGENT_MAX_STEPS, 8),
  },

  security: {
    apiKey: process.env.COO_API_KEY || '',
    // เปิด auth เฉพาะเมื่อมีการตั้ง COO_API_KEY ไว้ (dev จะรันได้เลย)
    get authEnabled() {
      return Boolean(process.env.COO_API_KEY);
    },
  },

  reportWebhookUrl: process.env.REPORT_WEBHOOK_URL || '',
  tz: process.env.TZ || 'Asia/Bangkok',
  debug: bool(process.env.DEBUG, false),
};

export default config;
