// use_figma, fileKey mgvOfQ9AizhhPMpBhxA3b5 — страница «Engineer · Dark» (3:7). Отложено: лимит MCP на Starter.
const page = await figma.getNodeByIdAsync('3:7');
await figma.setCurrentPageAsync(page);
if (page.children.length) return { skipped: true };
const vars = await figma.variables.getLocalVariablesAsync();
const cols = await figma.variables.getLocalVariableCollectionsAsync();
const LID = cols.find(c => c.name === 'Color Light').id;
const DID = cols.find(c => c.name === 'Color Dark').id;
const C = (n, col = LID) => vars.find(x => x.name === n && x.variableCollectionId === col);
const paint = n => figma.variables.setBoundVariableForPaint({ type: 'SOLID', color: { r: 0, g: 0, b: 0 } }, 'color', C(n));
const styles = await figma.getLocalTextStylesAsync();
const TS = n => styles.find(s => s.name === n).id;
await Promise.all(['Regular','Medium','Semi Bold','Bold'].map(style => figma.loadFontAsync({ family: 'Inter', style })));
const txt = async (parent, chars, style, color = 'fg') => { const t = figma.createText(); parent.appendChild(t); await t.setTextStyleIdAsync(TS(style)); t.characters = chars; t.fills = [paint(color)]; return t; };
const col = (name, gap) => { const f = figma.createAutoLayout('VERTICAL', { name, itemSpacing: gap }); f.fills = []; return f; };
const row = (name, gap) => { const f = figma.createAutoLayout('HORIZONTAL', { name, itemSpacing: gap }); f.fills = []; return f; };
const comps = await figma.getNodeByIdAsync('3:6');
const set = name => comps.children.find(n => n.name === name);
const variant = (setName, vname) => set(setName).children.find(v => v.name === vname);
const label = (inst, text) => inst.setProperties({ [Object.keys(inst.componentProperties).find(k => k.startsWith('Label'))]: text });

const screen = col('Кабинет инженера — тёмная тема', 0);
page.appendChild(screen);
screen.primaryAxisSizingMode = 'AUTO'; screen.counterAxisSizingMode = 'FIXED'; screen.resize(1440, 100);
screen.fills = [paint('canvas')];
const header = row('Header', 16); screen.appendChild(header);
header.layoutSizingHorizontal = 'FILL'; header.primaryAxisAlignItems = 'SPACE_BETWEEN'; header.counterAxisAlignItems = 'CENTER';
header.paddingLeft = header.paddingRight = 24; header.paddingTop = header.paddingBottom = 12;
header.fills = [paint('surface')]; header.strokes = [paint('border')]; header.strokeAlign = 'INSIDE';
header.strokeTopWeight = 0; header.strokeLeftWeight = 0; header.strokeRightWeight = 0; header.strokeBottomWeight = 1;
await txt(header, 'EV-ServiceDesk — Кабинет инженера', 'web/h2');
const tbtn = variant('Button', 'Style=Secondary, Size=Web SM, State=Default').createInstance(); header.appendChild(tbtn); label(tbtn, 'Светлая тема');
const main = col('Main', 24); screen.appendChild(main);
main.layoutSizingHorizontal = 'FILL'; main.paddingLeft = main.paddingRight = 240; main.paddingTop = main.paddingBottom = 32;
const card = (title) => { const c = col(title, 12); c.fills = [paint('surface')]; c.strokes = [paint('border')]; c.strokeAlign = 'INSIDE'; c.cornerRadius = 12; c.paddingLeft = c.paddingRight = c.paddingTop = c.paddingBottom = 16; return c; };
const c1 = card('Статусы'); main.appendChild(c1); c1.layoutSizingHorizontal = 'FILL';
await txt(c1, 'Статусы агрегатов — Zeekr 001, VIN LB37622Z0NX000000', 'web/h3');
const br = row('Badges', 8); c1.appendChild(br);
for (const s of ['Green', 'Yellow', 'Red', 'Unknown']) br.appendChild(variant('StatusBadge', `Status=${s}`).createInstance());
const c2 = card('Тикет'); main.appendChild(c2); c2.layoutSizingHorizontal = 'FILL';
await txt(c2, 'Тикет #1042 — «Не работает CarPlay после русификации»', 'web/h3');
await txt(c2, 'SLA: 3 ч 20 мин до нарушения. Клиент: владелец Zeekr 001.', 'web/body', 'fg-muted');
const bt = row('Buttons', 8); c2.appendChild(bt);
for (const [st, l] of [['Primary', 'Взять в работу'], ['Secondary', 'Ответить'], ['Ghost', 'Отмена'], ['Danger', 'Закрыть тикет']]) {
  const b = variant('Button', `Style=${st}, Size=Web, State=Default`).createInstance(); bt.appendChild(b); label(b, l);
}
const dis = variant('Button', 'Style=Primary, Size=Web, State=Disabled').createInstance(); bt.appendChild(dis); label(dis, 'Недоступно');
const c3 = card('Поля'); main.appendChild(c3); c3.layoutSizingHorizontal = 'FILL';
const fr = row('Fields', 24); c3.appendChild(fr);
for (const st of ['Default', 'Focus', 'Error']) fr.appendChild(variant('TextField', `State=${st}, Platform=Web`).createInstance());
const cards = row('Cards', 24); main.appendChild(cards);
for (let i = 0; i < 2; i++) cards.appendChild(set('Card').createInstance());

// Color Light → Color Dark по имени переменной (Starter: 1 режим на коллекцию)
const lightToDark = new Map(vars.filter(v => v.variableCollectionId === LID).map(v => [v.id, C(v.name, DID)]));
let rebound = 0;
const rebind = (paints) => paints.map(p => {
  const id = p.boundVariables?.color?.id;
  if (p.type === 'SOLID' && id && lightToDark.has(id)) { rebound++; return figma.variables.setBoundVariableForPaint(p, 'color', lightToDark.get(id)); }
  return p;
});
for (const n of [screen, ...screen.findAll(() => true)]) {
  if ('fills' in n && Array.isArray(n.fills) && n.fills.length) n.fills = rebind(n.fills);
  if ('strokes' in n && n.strokes.length) n.strokes = rebind(n.strokes);
}
screen.x = 0; screen.y = 0;
await screen.screenshot({ scale: 0.6 });
return { screen: screen.id, rebound, size: [screen.width, screen.height] };
