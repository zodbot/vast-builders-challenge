import fs from 'node:fs/promises';
import path from 'node:path';
const { Workbook, SpreadsheetFile } = await import(process.env.PROPERTY_ARTIFACT_MODULE || '@oai/artifact-tool');
const [input, output, flag] = process.argv.slice(2);
const spec = JSON.parse(await fs.readFile(input, 'utf8'));
const wb = Workbook.create();
const names = ['Summary', 'Inputs', 'Rental Operations', 'Amortization', 'Rent vs Buy', 'Sensitivity', 'Sales Comps', 'Rental Comps', 'Property Evidence', 'HOA Questions', 'Sources'];
const sheets = Object.fromEntries(names.map(n => [n, wb.worksheets.add(n)]));
const money = '$#,##0.00;($#,##0.00);"–"';
const safe = x => typeof x === 'string' && /^[=+@-]/.test(x) ? "'" + x : x;
function text(sheet, cell, value) { sheet.getRange(cell).values = [[safe(value ?? '')]]; }
for (const [name, sh] of Object.entries(sheets)) {
  sh.showGridLines = false;
  sh.getRange('A1:B45').format.columnWidth = 2;
  sh.getRange('C1:J45').format.font.name = 'Arial';
  sh.getRange('C1:J45').format.font.size = 10;
  sh.getRange('C1:C45').format.columnWidth = 48;
  sh.getRange('D1:D45').format.columnWidth = 23;
  sh.getRange('E1:E45').format.columnWidth = 3;
  sh.getRange('F1:F45').format.columnWidth = 80;
  text(sh, 'C2', name);
  sh.getRange('C2').format.font.size = 16;
  sh.getRange('C2').format.font.bold = true;
  text(sh, 'C3', spec.address);
  text(sh, 'F3', `${spec.mode === 'synthetic' ? 'SYNTHETIC DEMONSTRATION' : 'Scenario assumptions'} · Version ${spec.version}`);
  sh.getRange('C4:F4').format.borders = {bottom:{style:'thin',color:'#274A45'}};
  if (name !== 'Summary') sh.freezePanes.freezeRows(5);
}
sheets.Summary.tabColor = '#173F38'; sheets.Inputs.tabColor = '#728E82';
for (const c of spec.finance.cells) {
  const sh = sheets[c.sheet];
  if (c.label_cell && c.label) text(sh, c.label_cell, c.label);
  if (!c.formula) text(sh, c.cell, c.value);
  if (c.note) {
    const row = c.cell.match(/\d+/)[0];
    text(sh, `F${row}`, c.note);
    sh.getRange(`F${row}`).format.wrapText = true;
    sh.getRange(`C${row}:F${row}`).format.rowHeight = 32;
  }
  const range = sh.getRange(c.cell);
  range.setNumberFormat(c.format === 'percent' ? '0.0%;(0.0%);"–"' : c.format === 'number' ? '#,##0.00' : money);
  if (c.input) { range.format.font.color = '#1764A1'; range.format.fill = c.value === null ? '#FFF1C9' : '#EDF4F1'; }
}
// Write each contiguous formula block once; inputs remain separately authored values.
for (const name of ['Summary','Rental Operations','Amortization','Rent vs Buy','Sensitivity']) {
  const cells = spec.finance.cells.filter(c => c.sheet === name && c.formula);
  const end = Math.max(...cells.map(c => Number(c.cell.match(/\d+/)[0])));
  const width = ['Summary','Rental Operations'].includes(name) ? 1 : name==='Sensitivity'?6:4;
  const matrix = Array.from({length:end-5},()=>Array(width).fill(null));
  for (const c of cells) matrix[Number(c.cell.match(/\d+/)[0])-6][c.cell.charCodeAt(0)-68] = c.formula;
  const range = sheets[name].getRange(`D6:${String.fromCharCode(67+width)}${end}`);
  range.formulas = matrix;
  range.setNumberFormat(money);
  range.format.font.color = name === 'Summary' ? '#173F38' : '#26704D';
}
for (const c of spec.finance.cells.filter(c=>c.format==='percent' && c.formula)) sheets[c.sheet].getRange(c.cell).setNumberFormat('0.0%;(0.0%);"–"');
for (const c of spec.finance.cells.filter(c=>c.format==='ratio')) sheets[c.sheet].getRange(c.cell).setNumberFormat('0.00"x"');
sheets.Sensitivity.getRange('C5:I5').values=[['Hypothetical case','Purchase price','Monthly rent','Monthly P&I','Annual NOI','Cap rate','Annual cash flow']];
sheets.Sensitivity.getRange('D5:I15').format.columnWidth=22;
text(sheets.Sensitivity,'C17','Tax budget scales with purchase price. Other costs stay fixed. These cases are not market forecasts.');
for (const name of ['Amortization','Rent vs Buy']) {
  const sh=sheets[name];
  const months = name === 'Amortization' ? Math.max(spec.assumptions.term_years,spec.assumptions.holding_years)*12 : spec.assumptions.holding_years*12;
  sh.getRange(`C6:C${months+5}`).values = Array.from({length:months},(_,i)=>[i+1]);
  sh.getRange(`C5:G${months+5}`).format.columnWidth = 21;
  sh.getRange(`C6:G${months+5}`).format.rowHeight = 19;
  sh.getRange('C5:G5').values = [name==='Amortization'?['Month','Payment','Interest','Principal','Balance']:['Month','Owner cash cost','Renter cash cost','Renter invested','Buyer invested']];
}
function table(name, headers, rows, widths) {
  const sh=sheets[name], last=String.fromCharCode(67+headers.length-1);
  sh.getRange(`C5:${last}5`).values=[headers];
  if (rows.length) sh.getRange(`C6:${last}${rows.length+5}`).values=rows.map(row=>row.map(safe));
  else text(sh,'C6','No reviewed records available');
  headers.forEach((_,i)=>sh.getRange(`${String.fromCharCode(67+i)}5:${String.fromCharCode(67+i)}${Math.max(6,rows.length+5)}`).format.columnWidth=widths?.[i]||24);
  sh.getRange(`C6:${last}${Math.max(6,rows.length+5)}`).format.wrapText=true;
  sh.getRange(`C6:${last}${Math.max(6,rows.length+5)}`).format.rowHeight=48;
}
for (const [category,name] of [['sale','Sales Comps'],['rent','Rental Comps']]) {
  table(name,['Address','Price','Price type','Event date','Status','Why comparable or excluded','Source ID'],spec.comps.filter(c=>c.category===category).map(c=>[c.address,Number(c.price),c.price_type,c.event_date||'Unknown',c.status,[c.rationale,...c.differences].join(' '),c.source_id]),[42,18,22,24,18,65,35]);
  sheets[name].getRange('D6:D40').setNumberFormat(money);
}
table('Property Evidence',['Claim','Evidence type','Review status','Sources','Limitation'],spec.claims.map(c=>[c.text,c.kind,c.status,c.source_ids.join(', '),c.limitation]),[65,18,22,35,65]);
table('HOA Questions',['Document or question','Why it matters','Status'],spec.questions.map(q=>[q.question,q.reason,q.status]),[48,80,20]);
table('Sources',['Source','Type','Retrieved','Event date','URL','Source ID'],spec.sources.map(s=>[s.title,s.kind,s.retrieved_at,s.event_date||'Unknown',s.url||'User supplied or synthetic',s.id]),[44,18,32,24,65,35]);
sheets.Sources.getRange(`E6:E${Math.max(6,spec.sources.length+5)}`).setNumberFormat('yyyy-mm-dd hh:mm');
sheets.Sources.getRange(`F6:F${Math.max(6,spec.sources.length+5)}`).setNumberFormat('yyyy-mm-dd');
for (const name of names.filter(n=>!['Summary','Inputs','Rental Operations'].includes(n))) {
  const sh=sheets[name];
  const end = name==='Sources'?'H':name.endsWith('Comps')||name==='Sensitivity'?'I':name==='HOA Questions'?'E':'G';
  sh.getRange(`C5:${end}5`).format.fill='#274A45';
  sh.getRange(`C5:${end}5`).format.font.color='#FFFFFF';
  sh.getRange(`C5:${end}5`).format.font.bold=true;
  sh.getRange(`C5:${end}5`).format.wrapText=true;
  sh.getRange(`C5:${end}5`).format.rowHeight=30;
}
spec.finance.notes.forEach((note,i)=>text(sheets.Summary,`C${27+i*2}`,note));
for (let i=0;i<spec.finance.notes.length;i++) {
  // Notes have a separate wide area to avoid obscuring any financial cells.
  const r=27+i*2; sheets.Summary.getRange(`C${r}:F${r}`).merge();
  sheets.Summary.getRange(`C${r}:F${r}`).format.wrapText=true;
  sheets.Summary.getRange(`C${r}:F${r}`).format.rowHeight=30;
}
wb.recalculate();
const mismatches=[];
for (const c of spec.finance.cells.filter(c=>c.sheet==='Summary' && c.formula)) {
  const actual=sheets.Summary.getRange(c.cell).values[0][0];
  if (c.value !== null && (typeof actual!=='number' || Math.abs(actual-c.value)>0.05)) mismatches.push({key:c.key,expected:c.value,actual});
}
if (mismatches.length) throw new Error('Calculation parity failed: '+JSON.stringify(mismatches));
const errors=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:10},maxChars:2000});
if (/#REF!|#DIV\/0!|#VALUE!|#NAME\?|#NUM!|#NULL!|#SPILL!|#CALC!/.test(errors.ndjson)) throw new Error('Spreadsheet formula errors: '+errors.ndjson);
await fs.writeFile(path.join(path.dirname(output),'workbook-checks.json'),JSON.stringify({parity:'passed',errorScan:errors.ndjson},null,2));
if (flag==='--verify') {
  const directory=path.join(path.dirname(output),'previews'); await fs.mkdir(directory,{recursive:true});
  for (const name of names) {
    const image=await wb.render({sheetName:name,range:name==='Summary'?'C1:F38':'C1:I14',scale:1,format:'png'});
    await fs.writeFile(path.join(directory,name.replaceAll(' ','-')+'.png'),new Uint8Array(await image.arrayBuffer()));
  }
  const price = spec.finance.cells.find(c=>c.key==='purchase_price');
  if (price?.value) {
    const old=sheets.Summary.getRange('D7').values[0][0];
    sheets.Inputs.getRange(price.cell).values=[[price.value*1.1]];
    wb.recalculate();
    const changed=sheets.Summary.getRange('D7').values[0][0];
    if (old && !(changed>old)) throw new Error('Input-change recalculation failed');
    sheets.Inputs.getRange(price.cell).values=[[price.value]]; wb.recalculate();
  }
}
await fs.mkdir(path.dirname(output),{recursive:true});
await (await SpreadsheetFile.exportXlsx(wb)).save(output);
console.log(JSON.stringify({output,parity:'passed',sheets:names.length}));
