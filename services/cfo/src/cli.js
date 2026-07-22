// Command-line entry points: `npm run brief`, `npm run monitor`.
import { runAnalysis, runBrief } from './service.js';
import { runOnce } from './scheduler.js';

const cmd = process.argv[2] || 'brief';

async function main() {
  if (cmd === 'brief') {
    const { brief } = await runBrief();
    console.log('\n' + brief.text + '\n');
    console.log(`— generated via: ${brief.source}${brief.error ? ` (fallback reason: ${brief.error})` : ''}`);
  } else if (cmd === 'monitor') {
    await runOnce('cli');
  } else if (cmd === 'analyze') {
    console.log(JSON.stringify(runAnalysis(), null, 2));
  } else {
    console.error(`Unknown command "${cmd}". Use: brief | monitor | analyze`);
    process.exit(1);
  }
}

main().catch((e) => { console.error(e); process.exit(1); });
