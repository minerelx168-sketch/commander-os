#!/usr/bin/env node
// run-brief.js — รัน agent loop หนึ่งรอบแล้วพิมพ์ COO Operational Brief ออกทาง stdout
import { runAgent } from '../src/agent/agentLoop.js';

const directive = process.argv.slice(2).join(' ') || undefined;

const result = await runAgent({ directive });
console.log('\n' + '─'.repeat(60));
console.log(result.brief.text);
console.log('─'.repeat(60));
console.log(`\n(provider=${result.provider}, steps=${result.steps}, actions=${result.actions.length})`);
