// What of the page's own text does not fit where it is shown: run in a browser, on the page as it
// stands (the card, the quick jumps, a popup, the credits), in each language and on each screen of
// the card. It returns one line for each piece of text that runs out of the box that holds it (the
// nearest box that cuts off what overflows, or the card itself), and for each box inside the card
// that scrolls sideways. An empty list is a pass. Text that only runs past the edge of a box that
// scrolls that way is not counted, that is what the box is for: below the card's list, or beyond
// the row of quick jumps on the map.
// (The tests in this folder run without a browser and cannot lay text out; the picture checks run
// this, and so can anyone in a browser's console: paste it and call it.)
() => {
  const out = [], seen = new Set();
  const say = (el, text, why) => { const line = `${why}: ${(el.id ? '#' + el.id : el.className || el.tagName).toString().slice(0, 30)} "${text.trim().slice(0, 40)}"`; if (!seen.has(line)) { seen.add(line); out.push(line); } };
  const shown = el => el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden';
  const roots = [...document.querySelectorAll('#panel, #jumps, .maplibregl-popup-content, .maplibregl-ctrl-attrib')].filter(shown);
  for (const top of roots) {
    const outer = top.getBoundingClientRect();
    const walker = document.createTreeWalker(top, NodeFilter.SHOW_TEXT, { acceptNode: n => (n.textContent.trim() ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT) });
    for (let node; (node = walker.nextNode());) {
      const el = node.parentElement;
      if (!shown(el)) continue;
      // the box that holds the text: the nearest one that cuts off what runs out of it
      let box = el, style = getComputedStyle(box);
      while (box !== top && style.overflowX === 'visible' && style.overflowY === 'visible') { box = box.parentElement; style = getComputedStyle(box); }
      const edge = box === top ? outer : box.getBoundingClientRect();
      const scrollsDown = /auto|scroll/.test(style.overflowY), scrollsSide = /auto|scroll/.test(style.overflowX);
      const range = document.createRange();
      range.selectNodeContents(node);
      for (const r of range.getClientRects()) {
        if (!r.width) continue;
        if (!scrollsSide && (r.right > edge.right + 0.5 || r.left < edge.left - 0.5)) say(el, node.textContent, 'runs out sideways');
        else if (!scrollsDown && (r.bottom > edge.bottom + 0.5 || r.top < edge.top - 0.5)) say(el, node.textContent, 'runs out below or above');
      }
      // a box that cuts its text short with an ellipsis
      if (getComputedStyle(el).textOverflow === 'ellipsis' && el.scrollWidth > el.clientWidth + 1) say(el, node.textContent, 'cut short');
    }
  }
  const panel = document.getElementById('panel');
  for (const el of panel ? panel.querySelectorAll('*') : []) {
    if (shown(el) && /auto|scroll/.test(getComputedStyle(el).overflowX) && el.scrollWidth > el.clientWidth + 1) say(el, el.textContent, 'scrolls sideways');
  }
  return out;
}
