/* Display geometry only. The routing/source coordinates remain authoritative. */
const ContinuousOffset = (() => {
  const smooth = t => { t = Math.max(0, Math.min(1, t)); return t ** 3 * (10 + t * (-15 + 6 * t)); };
  const length = co => co.slice(1).reduce((s, p, i) => s + Math.hypot(p[0] - co[i][0], p[1] - co[i][1]), 0);
  const identity = p => JSON.stringify(['g', 'r', 'ct', 'network', 'rid', 'n', 'col', 'zf', 'zn'].map(k => p[k] ?? null));
  const endpoint = p => JSON.stringify(p);
  const fields = ['off', 'goff', 'sh'];
  const rampSize = .004;
  const strokeContexts = new WeakMap();
  function lowerBound(values, at) {
    let lo = 0, hi = values.length;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (values[mid] < at) lo = mid + 1; else hi = mid; }
    return lo;
  }
  function parse(value) {
    if (!value) return null;
    const p = typeof value === 'string' ? JSON.parse(value) : value;
    const origin = p?.origin ?? 0, direction = p?.direction ?? 1, period = p?.period ?? null;
    if (p?.v !== 1 || !Number.isFinite(p.base) || !Number.isFinite(origin) || ![1, -1].includes(direction)
      || (period !== null && (!Number.isFinite(period) || period <= 0)) || !Array.isArray(p.ramps)
      || p.ramps.some((r, i) => !Array.isArray(r) || r.length !== 4 || !r.every(Number.isFinite)
        || r[1] <= r[0] || (i && r[0] < p.ramps[i - 1][1]))) throw Error('Invalid offset profile');
    return { ...p, origin, direction, period };
  }
  function value(p, d) {
    let at = (p.origin || 0) + (p.direction || 1) * d;
    if (p.period) at = ((at % p.period) + p.period) % p.period;
    const before = x => {
      let lo = 0, hi = p.ramps.length;
      while (lo < hi) { const mid = (lo + hi) >> 1; if (p.ramps[mid][0] <= x) lo = mid + 1; else hi = mid; }
      return lo - 1;
    };
    let i = before(at), j = p.period ? before(at + p.period) : -1;
    if (i > 0 && p.ramps[i - 1][1] === at) i--;
    if (j > 0 && p.ramps[j - 1][1] === at + p.period) j--;
    const active = i >= 0 && at <= p.ramps[i][1];
    const wrapped = j >= 0 && at + p.period <= p.ramps[j][1];
    if (active || wrapped) {
      const useWrapped = wrapped && (!active || j < i), x = useWrapped ? at + p.period : at;
      const [lo, hi, a, b] = p.ramps[useWrapped ? j : i];
      return (p.direction || 1) * (a + (b - a) * smooth((x - lo) / (hi - lo)));
    }
    return (p.direction || 1) * (i >= 0 ? p.ramps[i][3] : p.base);
  }
  const mercator = ([x, y]) => [x / 360, -Math.log(Math.tan(Math.PI / 4 + y * Math.PI / 360)) / (2 * Math.PI)];
  const lnglat = ([x, y]) => [x * 360, (2 * Math.atan(Math.exp(-y * 2 * Math.PI)) - Math.PI / 2) * 180 / Math.PI];
  function prepare(features) {
    const parts = [], ports = new Map();
    for (const f of features) {
      const lines = f.geometry.type === 'MultiLineString' ? f.geometry.coordinates : [f.geometry.coordinates];
      for (const coords of lines) {
        if (coords.length < 2) continue;
        const p = { f, coords, len: length(coords), key: identity(f.properties), profile: parse(f.properties.op) };
        if (!p.len) continue;
        const i = parts.push(p) - 1;
        for (const end of [0, -1]) {
          const key = p.key + endpoint(coords.at(end));
          if (!ports.has(key)) ports.set(key, []);
          ports.get(key).push([i, end]);
        }
      }
    }
    const used = new Set(), chains = [];
    for (let seed = 0; seed < parts.length; seed++) {
      if (used.has(seed)) continue;
      let current = seed, end = 0;
      const seen = new Set();
      while (!seen.has(current)) {
        seen.add(current);
        const p = parts[current], port = ports.get(p.key + endpoint(p.coords.at(end)));
        if (port.length !== 2) break;
        const other = port.find(([i]) => i !== current);
        if (!other) break;
        [current, end] = other;
        end = end === 0 ? -1 : 0;
      }
      if (seen.has(current) && ports.get(parts[current].key + endpoint(parts[current].coords.at(end))).length === 2) {
        current = seed; end = 0;
      }
      const co = [], members = [];
      let at = 0;
      while (!used.has(current)) {
        used.add(current);
        const p = parts[current], sign = end === 0 ? 1 : -1;
        const coords = sign === 1 ? p.coords : [...p.coords].reverse();
        const first = co.length ? co.length - 1 : 0;
        members.push({ ...p, start: at, end: at + p.len, sign, first, last: first + coords.length - 1 });
        for (let i = co.length ? 1 : 0; i < coords.length; i++) co.push(coords[i]);
        at += p.len;
        const port = ports.get(p.key + endpoint(coords.at(-1)));
        if (port.length !== 2) break;
        const other = port.find(([i]) => i !== current && !used.has(i));
        if (!other) break;
        [current, end] = other;
      }
      const closed = endpoint(co[0]) === endpoint(co.at(-1));
      const distances = [0];
      for (let i = 1; i < co.length; i++) distances.push(distances.at(-1) + Math.hypot(co[i][0] - co[i - 1][0], co[i][1] - co[i - 1][1]));
      const points = co.map(mercator);
      const tangents = points.slice(1).map((p, i) => {
        const dx = p[0] - points[i][0], dy = p[1] - points[i][1], n = Math.hypot(dx, dy);
        return n ? [dx / n, dy / n] : [0, 0];
      });
      const normals = points.map((_, i) => {
        const a = tangents[i ? i - 1 : closed ? tangents.length - 1 : 0];
        const b = tangents[i < tangents.length ? i : closed ? 0 : tangents.length - 1];
        const x = a[0] + b[0], y = a[1] + b[1], den = 1 + a[0] * b[0] + a[1] * b[1];
        // Bounded miter: sharp source corners must not create huge excursions.
        const scale = den > .5 ? 1 / den : 1 / Math.max(Math.hypot(x, y), 1e-12);
        return [-y * scale, x * scale];
      });
      const ramps = [];
      const pairs = members.slice(1).map((b, i) => [members[i], b]);
      if (closed) pairs.push([members.at(-1), { ...members[0], start: at, end: at + members[0].len }]);
      for (const [a, b] of pairs) {
        const pa = a.f.properties, pb = b.f.properties;
        const va = fields.map(k => k === 'sh' ? pa[k] || 0 : (pa[k] || 0) * a.sign);
        const vb = fields.map(k => k === 'sh' ? pb[k] || 0 : (pb[k] || 0) * b.sign);
        if (a.profile) va[0] = value(a.profile, a.sign === 1 ? a.len : 0) * a.sign;
        if (b.profile) vb[0] = value(b.profile, b.sign === 1 ? 0 : b.len) * b.sign;
        const mask = va.map((v, i) => i !== 0 || !(a.profile || b.profile) || Math.abs(v - vb[i]) > 1e-9);
        if (va.every((v, i) => Math.abs(v - vb[i]) <= 1e-9)) continue;
        const ra = Math.min(rampSize, a.len * .45), rb = Math.min(rampSize, b.len * .45);
        const count = p => p.bn || (p.off ? 2 : 1);
        const lo = count(pa) < count(pb) ? a.end - ra : count(pa) > count(pb) ? b.start : a.end - ra / 2;
        const hi = count(pa) < count(pb) ? a.end : count(pa) > count(pb) ? b.start + rb : b.start + rb / 2;
        ramps.push([lo, hi, va, vb, mask]);
      }
      // Migrate the old eased staircase as one monotone transition, not a
      // separate flat-ended curve for every quantised seat.
      const joinedRamps = [];
      for (const cut of ramps) {
        const previous = joinedRamps.at(-1);
        const follows = previous && cut[0] - previous[1] <= rampSize / 2
          && previous[4].every((v, i) => v === cut[4][i])
          && previous[3].every((v, i) => v === cut[2][i])
          && cut[3].every((v, i) => (v - cut[2][i]) * (previous[3][i] - previous[2][i]) >= 0)
          && (cut[3][0] - cut[2][0]) * (previous[3][0] - previous[2][0]) > 0;
        if (follows) { previous[1] = cut[1]; previous[3] = cut[3]; }
        else joinedRamps.push([...cut]);
      }
      // At an ambiguous same-line branch, a common zero-offset port is the
      // only source-supported anchor; do not guess a continuation through it.
      const anchors = [];
      if (!closed) for (const [m, start] of [[members[0], true], [members.at(-1), false]]) {
        const vertex = start ? co[0] : co.at(-1);
        const local = (start === (m.sign === 1)) ? 0 : m.len;
        const explicitCentre = m.f.properties.jc && m.profile && Math.abs(value(m.profile, local)) < 1e-9
          && !m.f.properties.goff && !m.f.properties.sh;
        if (ports.get(m.key + endpoint(vertex)).length > 2 && !explicitCentre) {
          const room = Math.min(rampSize, m.len * .45);
          anchors.push(start ? [0, room, true] : [at - room, at, false]);
        }
      }
      const box = co.reduce((b, p) => [Math.min(b[0], p[0]), Math.min(b[1], p[1]), Math.max(b[2], p[0]), Math.max(b[3], p[1])],
        [Infinity, Infinity, -Infinity, -Infinity]);
      const blocks = [];
      for (let first = 0; first < co.length - 1; first += 64) {
        const last = Math.min(first + 64, co.length - 1);
        const box = [Infinity, Infinity, -Infinity, -Infinity];
        for (let i = first; i <= last; i++) {
          box[0] = Math.min(box[0], co[i][0]); box[1] = Math.min(box[1], co[i][1]);
          box[2] = Math.max(box[2], co[i][0]); box[3] = Math.max(box[3], co[i][1]);
        }
        blocks.push({ first, last, box });
      }
      // Two bounds on the miter and on the seat/group contribution keep
      // shifted lines that enter the viewport even when their source is outside.
      let maxSeat = 1;
      for (const member of members) {
        const p = member.f.properties;
        let off = Math.abs(p.off || 0);
        if (member.profile) {
          off = Math.max(off, Math.abs(member.profile.base));
          for (const ramp of member.profile.ramps) off = Math.max(off, Math.abs(ramp[2]), Math.abs(ramp[3]));
        }
        maxSeat = Math.max(maxSeat, (off + 2 * Math.abs(p.goff || 0))
          * Math.max(1, Math.abs(p.sh || 0), Math.abs(1 - (p.sh || 0))));
      }
      chains.push({ co, members, distances, points, normals, ramps: joinedRamps, anchors, closed, len: at, box, blocks, maxSeat });
    }
    return chains;
  }
  function bindStroke(props, chain, member, from, to) {
    const at = d => member.sign === 1 ? member.start + d : member.end - d;
    strokeContexts.set(props, { chain, member, start: Math.min(at(from), at(to)), end: Math.max(at(from), at(to)) });
  }
  function renderStrokes(features, zoom, mode) {
    const plain = [], selected = new Map();
    for (const f of features) {
      const context = strokeContexts.get(f.properties);
      if (!context) { plain.push(f); continue; }
      if (!selected.has(context.chain)) selected.set(context.chain, []);
      selected.get(context.chain).push({ ...context, f });
    }
    return { type: 'FeatureCollection', features: [
      ...render(prepare(plain), zoom, mode).features,
      ...render([...selected.keys()], zoom, mode, null, selected).features] };
  }
  function offsetValues(chain, member, at, out, ramps = chain.ramps) {
    const p = member.f.properties;
    const local = member.sign === 1 ? at - member.start : member.end - at;
    let off = (p.off || 0) * member.sign, group = (p.goff || 0) * member.sign, shared = p.sh || 0;
    if (member.profile) off = value(member.profile, local) * member.sign;
    for (const [lo, hi, a, b, mask] of ramps) {
      let x = at;
      if (chain.closed && at < lo) x += chain.len;
      if (x >= lo && x <= hi) {
        const weight = smooth((x - lo) / (hi - lo));
        if (mask[0]) off = a[0] + (b[0] - a[0]) * weight;
        if (mask[1]) group = a[1] + (b[1] - a[1]) * weight;
        if (mask[2]) shared = a[2] + (b[2] - a[2]) * weight;
      }
    }
    for (const [lo, hi, start] of chain.anchors) {
      if (at >= lo && at <= hi) {
        const weight = smooth((at - lo) / (hi - lo));
        off *= start ? weight : 1 - weight;
        group *= start ? weight : 1 - weight;
      }
    }
    out.off = off; out.goff = group; out.sh = shared;
    return out;
  }
  function properties(chain, member, at) {
    return offsetValues(chain, member, at, { ...member.f.properties });
  }
  const stepStops = [[6, 1.8], [9, 3.2], [12, 5], [16, 8]];
  // light rail and trams, in every country: a quarter of a line width apart at every zoom
  // (src/app.html's TRAM_GUEST.step: its TRAM_STOPS widths times TRAM_GAP)
  const tramStepStops = [[4.5, 0.375], [9, 1], [10, 1.375], [11, 1.75], [12, 2], [13, 2.25], [14, 2.625], [15, 3.75], [16, 5.625]];
  const stepAt = (z, stops = stepStops) => {
    if (z <= stops[0][0]) return stops[0][1];
    if (z >= stops.at(-1)[0]) return stops.at(-1)[1];
    const i = stops.findIndex(([at]) => at > z) - 1;
    const [[z0, v0], [z1, v1]] = stops.slice(i, i + 2);
    return v0 + (v1 - v0) * (z - z0) / (z1 - z0);
  };
  function pixels(p, z, mode) {
    const stops = mode === 'metro' && p.jk === 'urban' ? tramStepStops : stepStops;
    const step = stepAt(z, stops), off = p.off ?? (mode === 'guest' ? 1 : 0), group = p.goff || 0, sh = p.sh || 0;
    if (mode === 'guest') return off * step;
    const separate = z <= 14.5 ? step : z >= 16.5 ? 0 : stepAt(14.5, stops) * (16.5 - z) / 2;
    if (mode === 'rail' || p.ap === 1) {
      const mixed = sh * step + (1 - sh) * separate;
      return off * mixed - group * (mixed - separate);
    }
    return off * step - group * (step - separate);
  }
  const intersects = (a, b) => !(a[2] < b[0] || a[0] > b[2] || a[3] < b[1] || a[1] > b[3]);
  function visibleRanges(chain, bounds, zoom) {
    if (!bounds) return [[0, chain.len]];
    const margin = 2 * chain.maxSeat * Math.max(stepAt(zoom), stepAt(zoom, tramStepStops)) * 360 / (512 * 2 ** zoom);
    const box = [bounds[0] - margin, bounds[1] - margin, bounds[2] + margin, bounds[3] + margin];
    if (!intersects(chain.box, box)) return [];
    if (chain.box[0] >= box[0] && chain.box[1] >= box[1] && chain.box[2] <= box[2] && chain.box[3] <= box[3]) return [[0, chain.len]];
    const ranges = [];
    for (const block of chain.blocks) {
      if (!intersects(block.box, box)) continue;
      for (let i = block.first; i < block.last; i++) {
        const a = chain.co[i], b = chain.co[i + 1];
        if (Math.max(a[0], b[0]) < box[0] || Math.min(a[0], b[0]) > box[2]
          || Math.max(a[1], b[1]) < box[1] || Math.min(a[1], b[1]) > box[3]) continue;
        const previous = ranges.at(-1), start = chain.distances[i], end = chain.distances[i + 1];
        if (previous && start === previous[1]) previous[1] = end;
        else ranges.push([start, end]);
      }
    }
    return ranges;
  }
  // A display fillet keeps the computed seat path, and replaces only a
  // small convex-hull corner. It does not change source/routing geometry,
  // endpoint ranks, the line width or the gap between parallel lines.
  function roundDisplay(co, zoom, parameters = null, sourceTurnbacks = null, sourceSimple = false) {
    if (co.length < 3) return parameters ? { co, at: parameters } : co;
    const world = 512 * 2 ** zoom;
    co = co.map(p=>[...p]);
    if (parameters) parameters=[...parameters];
    const turns=sourceTurnbacks ? [...sourceTurnbacks] : null, clippedRanges=[];
    const points = co.map(mercator);
    const originalPoints=points.map(p=>[...p]), originalParameters=parameters ? [...parameters] : null;
    // A local closed loop on an offset of a proven simple source part is
    // also a display artefact. Contract only loops whose complete original
    // parameter interval fits the same small displacement budget.
    const contractLoops = (points, co, parameters, turns = null) => {
      if (!sourceSimple || !parameters) return;
      const cross=(a,b)=>a[0]*b[1]-a[1]*b[0];
      for (let pass=0;pass<4;pass++) {
        let removed=false;
        outer: for(let i=0;i<points.length-2;i++) for(let j=i+2;j<points.length-1;j++) {
          const a=points[i],b=points[i+1],c=points[j],d=points[j+1];
          if (Math.max(a[0],b[0])<Math.min(c[0],d[0]) || Math.min(a[0],b[0])>Math.max(c[0],d[0])
            || Math.max(a[1],b[1])<Math.min(c[1],d[1]) || Math.min(a[1],b[1])>Math.max(c[1],d[1])) continue;
          const r=[b[0]-a[0],b[1]-a[1]],s=[d[0]-c[0],d[1]-c[1]],v=[c[0]-a[0],c[1]-a[1]],den=cross(r,s);
          if (!den) continue;
          const t=cross(v,s)/den,u=cross(v,r)/den;
          if(t<0 || t>1 || u<0 || u>1) continue;
          const point=[a[0]+t*r[0],a[1]+t*r[1]],ll=lnglat(point);
          const lo=parameters[i]+t*(parameters[i+1]-parameters[i]),hi=parameters[j]+u*(parameters[j+1]-parameters[j]);
          if (hi<=lo) continue;
          const bound=Math.min(10/world,18/(40075016.686*Math.cos(ll[1]*Math.PI/180)));
          if (originalPoints.some((p,k)=>originalParameters[k]>=lo && originalParameters[k]<=hi && Math.hypot(p[0]-point[0],p[1]-point[1])>bound)) continue;
          clippedRanges.push([lo,hi]);
          points.splice(i+1,j-i,point,[...point]);co.splice(i+1,j-i,ll,[...ll]);
          parameters.splice(i+1,j-i,lo,hi);turns?.splice(i+1,j-i,true,true);
          removed=true;break outer;
        }
        if(!removed) break;
      }
    };
    contractLoops(points, co, parameters, turns);
    // A sharp return introduced by the seat offset is not a source turnback.
    // Clip only its small triangular spur, with exact prefix/suffix/endpoints
    // retained. Actual source turnbacks and excursions beyond the bound stay.
    if (turns && parameters) for (let pass=0;pass<2;pass++) {
      for (let i=1;i<points.length-1;i++) {
        if (turns[i]) continue;
        const a=points[i-1],b=points[i],c=points[i+1];
        const u=[b[0]-a[0],b[1]-a[1]],v=[c[0]-b[0],c[1]-b[1]],den=Math.hypot(...u)*Math.hypot(...v);
        if (!den || (u[0]*v[0]+u[1]*v[1])/den>=-.8) continue;
        const dx=c[0]-a[0],dy=c[1]-a[1],length=dx*dx+dy*dy;
        if (!length) continue;
        const t=Math.max(0,Math.min(1,((b[0]-a[0])*dx+(b[1]-a[1])*dy)/length));
        const bound=Math.min(10/world,18/(40075016.686*Math.cos(co[i][1]*Math.PI/180)));
        const originals=originalPoints.filter((_,j)=>originalParameters[j]>=parameters[i-1] && originalParameters[j]<=parameters[i+1]);
        const outside=originals.some(p=>{
          const t=Math.max(0,Math.min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/length));
          return Math.hypot(p[0]-a[0]-t*dx,p[1]-a[1]-t*dy)>bound;
        });
        if (outside) continue;
        clippedRanges.push([parameters[i-1],parameters[i+1]]);
        points.splice(i,1);co.splice(i,1);parameters?.splice(i,1);turns.splice(i,1);i--;
      }
    }
    const out = [points[0]], at = [parameters?.[0]];
    const append = (p, d) => {
      const last = out.at(-1);
      if (Math.hypot(p[0] - last[0], p[1] - last[1]) * world > 1e-7 || parameters && d > at.at(-1) + 1e-15) { out.push(p); at.push(d); }
    };
    for (let i = 1; i < points.length - 1; i++) {
      const a = points[i - 1], b = points[i], c = points[i + 1];
      const before = Math.hypot(b[0] - a[0], b[1] - a[1]);
      const after = Math.hypot(c[0] - b[0], c[1] - b[1]);
      if (!before || !after) { append(b, parameters?.[i]); continue; }
      const u = [(b[0] - a[0]) / before, (b[1] - a[1]) / before];
      const v = [(c[0] - b[0]) / after, (c[1] - b[1]) / after];
      const dot = u[0] * v[0] + u[1] * v[1];
      // Keep real turnbacks. The combined spur/fillet budget is 24 m / 12 px. This limits displacement
      // at low zoom, where a large fixed screen-space radius would cut track.
      if ((dot < -.8 && (!turns || turns[i])) || dot < -.99999 || dot > .999999) { append(b, parameters?.[i]); continue; }
      const clipped = parameters && clippedRanges.some(([lo,hi])=>lo<=parameters[i+1] && hi>=parameters[i-1]);
      const metric = (clipped ? 6 : 12) / (40075016.686 * Math.cos(co[i][1] * Math.PI / 180));
      const trim = Math.min(before / 2, after / 2, (clipped ? 2 : 8) / world, metric);
      const entry = [b[0] - u[0] * trim, b[1] - u[1] * trim];
      const exit = [b[0] + v[0] * trim, b[1] + v[1] * trim];
      const entryAt = parameters ? parameters[i] - (parameters[i]-parameters[i-1])*trim/before : 0;
      const exitAt = parameters ? parameters[i] + (parameters[i+1]-parameters[i])*trim/after : 0;
      const parameter = t => (1-t)**2*entryAt+2*t*(1-t)*(parameters?.[i] || 0)+t*t*exitAt;
      append(entry, entryAt);
      const curve = t => [(1-t)**2 * entry[0] + 2*t*(1-t)*b[0] + t*t*exit[0],
        (1-t)**2 * entry[1] + 2*t*(1-t)*b[1] + t*t*exit[1]];
      function sample(lo, hi, pa, pb, depth) {
        const mid = (lo + hi) / 2, pm = curve(mid);
        const error = Math.hypot(pm[0] - (pa[0]+pb[0])/2, pm[1] - (pa[1]+pb[1])/2) * world;
        if (depth < 12 && error > .02) { sample(lo,mid,pa,pm,depth+1); sample(mid,hi,pm,pb,depth+1); }
        else append(pb, parameter(hi));
      }
      sample(0,1,entry,exit,0);
    }
    append(points.at(-1), parameters?.at(-1));
    // Fillets can reconnect the two sides of a previously clipped offset
    // spur. Recheck the final path with the same original-source bound, and
    // preserve its collapsed parameter interval for partial highlights.
    contractLoops(out, out.map(lnglat), parameters ? at : null);
    return parameters ? { co: out.map(lnglat), at } : out.map(lnglat);
  }
  function render(chains, zoom, mode, bounds = null, selected = null) {
    const features = [], world = 512 * 2 ** zoom;
    for (const chain of chains) {
      const ranges = visibleRanges(chain, bounds, zoom);
      if (!ranges.length) continue;
      const members = selected?.get(chain) || chain.members.map(member => ({
        member, start: member.start, end: member.end, f: member.f }));
      for (const { member, start: memberStart, end: memberEnd, f } of members) {
      const drawStart = member.f.properties.jc && selected ? member.start : memberStart;
      const drawEnd = member.f.properties.jc && selected ? member.end : memberEnd;
      const ramps = chain.ramps.filter(([lo, hi]) => hi >= drawStart && lo <= drawEnd
        || chain.closed && hi >= memberStart + chain.len && lo <= memberEnd + chain.len);
      // (jk chooses the step: light rail and trams are one thin line width apart)
      const { ap, jk } = member.f.properties, state = { ap, jk };
      // A zero-seat common branch port uses the normal of this shared
      // member edge. A through chain's bisector and a branching chain's end
      // normal otherwise disagree over the same centre segment and cross
      // before reaching their identical zero-offset endpoint.
      const portNormals = new Map();
      if (member.f.properties.jc && member.profile) for (const begin of [true, false]) {
        const index = begin ? member.first : member.last;
        const local = (begin === (member.sign === 1)) ? 0 : member.len;
        if (Math.abs(value(member.profile, local)) > 1e-9) continue;
        let other = index + (begin ? 1 : -1);
        while (other >= member.first && other <= member.last &&
          Math.hypot(chain.points[other][0]-chain.points[index][0],chain.points[other][1]-chain.points[index][1]) < 1e-15)
          other += begin ? 1 : -1;
        if (other < member.first || other > member.last) continue;
        const a = chain.points[begin ? index : other], b = chain.points[begin ? other : index];
        const dx=b[0]-a[0],dy=b[1]-a[1],length=Math.hypot(dx,dy);
        portNormals.set(index,[-dy/length,dx/length]);
      }
      const normal = i => portNormals.get(i) || chain.normals[i];
      const shifted = at => {
        let lo = 0, hi = chain.distances.length - 1;
        while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (chain.distances[mid] <= at) lo = mid; else hi = mid; }
        const d = chain.distances[hi] - chain.distances[lo], t = d ? (at - chain.distances[lo]) / d : 0;
        // Interpolate original WGS84 geometry, not a Mercator chord.
        const a = chain.co[lo], b = chain.co[hi], na = normal(lo), nb = normal(hi);
        const point = t === 0 ? chain.points[lo] : t === 1 ? chain.points[hi]
          : mercator([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]);
        const px = pixels(offsetValues(chain, member, at, state, ramps), zoom, mode) / world;
        return [point[0] + (na[0] + (nb[0] - na[0]) * t) * px,
          point[1] + (na[1] + (nb[1] - na[1]) * t) * px, a[1] + (b[1] - a[1]) * t];
      };
      for (const [rangeStart, rangeEnd] of ranges) {
      const start = Math.max(drawStart, rangeStart), end = Math.min(drawEnd, rangeEnd);
      if (end <= start) continue;
      const first = lowerBound(chain.distances, start), last = lowerBound(chain.distances, end);
      const positions = [start, ...chain.distances.slice(first, last).filter(d => d > start), end];
      const transitions = [];
      for (const [lo, hi] of chain.ramps) for (const at of [lo, hi]) {
        for (const pos of chain.closed ? [at, at - chain.len] : [at]) {
          if (pos > start && pos < end) positions.push(pos);
        }
      }
      for (const [lo, hi] of ramps) {
        transitions.push([lo, hi]);
        if (chain.closed) transitions.push([lo - chain.len, hi - chain.len]);
      }
      if (member.profile) for (const [lo, hi] of member.profile.ramps) for (const d of [lo, hi]) {
        for (const at of member.profile.period ? [d, d - member.profile.period] : [d]) {
          const local = (at - member.profile.origin) / member.profile.direction;
          const pos = member.sign === 1 ? member.start + local : member.end - local;
          if (pos > start && pos < end) positions.push(pos);
        }
      }
      if (member.profile) for (const [lo, hi] of member.profile.ramps) {
        const toChain = d => {
          const local = (d - member.profile.origin) / member.profile.direction;
          return member.sign === 1 ? member.start + local : member.end - local;
        };
        for (const shift of member.profile.period ? [0, -member.profile.period] : [0]) {
          const a = toChain(lo + shift), b = toChain(hi + shift);
          transitions.push([Math.min(a, b), Math.max(a, b)]);
        }
      }
      for (const [lo, hi] of chain.anchors) for (const at of [lo, hi]) {
        if (at > start && at < end) positions.push(at);
      }
      transitions.push(...chain.anchors);
      transitions.sort((a, b) => a[0] - b[0]);
      const varying = [];
      for (const [lo, hi] of transitions) {
        const previous = varying.at(-1);
        if (previous && lo <= previous[1]) previous[1] = Math.max(previous[1], hi);
        else varying.push([lo, hi]);
      }
      positions.sort((a, b) => a - b);
      let previous = shifted(positions[0]);
      const co = [lnglat(previous)], parameters = [positions[0]];
      function sample(a, b, pa, pb, depth) {
        const m = (a + b) / 2, pm = shifted(m);
        const error = Math.hypot(pm[0] - (pa[0] + pb[0]) / 2, pm[1] - (pa[1] + pb[1]) / 2) * world;
        // Include quarter points: a symmetric S curve has zero midpoint error.
        const q = shifted((3 * a + b) / 4), r = shifted((a + 3 * b) / 4);
        const err = Math.max(error, Math.hypot(q[0] - (.75 * pa[0] + .25 * pb[0]), q[1] - (.75 * pa[1] + .25 * pb[1])) * world,
          Math.hypot(r[0] - (.25 * pa[0] + .75 * pb[0]), r[1] - (.25 * pa[1] + .75 * pb[1])) * world);
        if (depth < 18 && err > .04) { sample(a, m, pa, pm, depth + 1); sample(m, b, pm, pb, depth + 1); }
        else { co.push(lnglat(pb)); parameters.push(b); }
      }
      let transition = 0;
      for (let i = 1; i < positions.length; i++) {
        if (positions[i] > positions[i - 1]) {
          const a = positions[i - 1], b = positions[i], next = shifted(b), mid = (a + b) / 2;
          while (transition < varying.length && varying[transition][1] < mid) transition++;
          const changes = transition < varying.length && varying[transition][0] < mid && varying[transition][1] > mid;
          const ya = previous[2], yb = next[2];
          // Constant seats and linearly interpolated normals are linear in
          // Mercator except for latitude projection. Its second derivative
          // bounds every interior chord error, avoiding three redundant probes.
          const latitude = Math.max(Math.abs(ya), Math.abs(yb)) * Math.PI / 180;
          const curvature = Math.PI * Math.abs(Math.sin(latitude)) / (64800 * Math.cos(latitude) ** 2);
          const projectionError = curvature * (yb - ya) ** 2 * world / 8;
          if (!changes && projectionError <= .04) { co.push(lnglat(next)); parameters.push(b); }
          else sample(a, b, previous, next, 0);
          previous = next;
        }
      }
      const p = { ...f.properties, _continuous: 1 };
      // Width/host decisions retain the original seat; line-offset is zero on
      // this independent display source. Reverse back to the source direction.
      let display = co;
      if (member.f.properties.jc) {
        const turnbacks=parameters.map(at=>{
          const i=lowerBound(chain.distances,at);
          if (!i || i>=chain.points.length-1 || Math.abs(chain.distances[i]-at)>1e-12) return false;
          const a=chain.points[i-1],b=chain.points[i],c=chain.points[i+1];
          const u=[b[0]-a[0],b[1]-a[1]],v=[c[0]-b[0],c[1]-b[1]],den=Math.hypot(...u)*Math.hypot(...v);
          return !den || (u[0]*v[0]+u[1]*v[1])/den<-.8;
        });
        const rounded = roundDisplay(co, zoom, parameters, turnbacks, !!member.f.properties.cl);
        display = rounded.co;
        if (selected) {
          const atPoint = at => {
            let i = Math.min(rounded.at.length - 1, lowerBound(rounded.at, at));
            if (!i || rounded.at[i] === at) return rounded.co[i];
            const t=(at-rounded.at[i-1])/(rounded.at[i]-rounded.at[i-1]);
            const a=mercator(rounded.co[i-1]), b=mercator(rounded.co[i]);
            return lnglat([a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t]);
          };
          display=[atPoint(memberStart), ...rounded.co.filter((_,i)=>rounded.at[i]>memberStart && rounded.at[i]<memberEnd), atPoint(memberEnd)];
        }
      }
      features.push({ ...f, properties: p, geometry: { type: 'LineString', coordinates: member.sign === 1 ? display : display.reverse() } });
      }
      }
    }
    return { type: 'FeatureCollection', features };
  }
  return { smooth, value, parse, prepare, properties, pixels, render, renderStrokes, bindStroke, mercator, identity, roundDisplay };
})();
