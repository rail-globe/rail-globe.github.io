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
    return { ...p, origin, direction, period, lo: p.lo ? parse(p.lo) : undefined };
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
    // A junction profile (op.jn) names, where its line meets three or more of
    // its own stretches, the stretch it runs on along (s: the spine) or the one
    // it leaves as a branch (t: the trunk), by that stretch's first drawn point
    // away from the node. A spine is chained through the node like any other
    // two-part port; every other port of three or more parts ends a chain.
    const awayOf = (i, end) => {
      const co = parts[i].coords, last = co.length - 1, at = end === 0 ? 0 : last, step = end === 0 ? 1 : -1;
      let k = at + step;
      while (k > 0 && k < last && endpoint(co[k]) === endpoint(co[at])) k += step;
      return endpoint(co[k]);
    };
    const joinOf = (i, end) => parts[i].profile?.jn?.[end === 0 ? 0 : 1] ?? null;
    const portOf = (i, end) => ports.get(parts[i].key + endpoint(parts[i].coords.at(end)));
    const link = (current, end, free = () => true) => {
      const port = portOf(current, end);
      if (port.length === 2) return port.find(([i]) => i !== current && free(i)) ?? null;
      const want = joinOf(current, end)?.s;
      if (!want) return null;
      const target = endpoint(want);
      return port.find(([i, e]) => i !== current && free(i) && joinOf(i, e)?.s && awayOf(i, e) === target) ?? null;
    };
    const used = new Set(), chains = [];
    for (let seed = 0; seed < parts.length; seed++) {
      if (used.has(seed)) continue;
      let current = seed, end = 0;
      const seen = new Set();
      while (!seen.has(current)) {
        seen.add(current);
        const other = link(current, end);
        if (!other) break;
        [current, end] = other;
        end = end === 0 ? -1 : 0;
      }
      if (seen.has(current) && (portOf(current, end).length === 2 || link(current, end))) {
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
        const other = link(current, sign === 1 ? -1 : 0, i => !used.has(i));
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
      // A junction profile naming the port's spine or trunk (op.jn) already
      // gives the port its seat (2026-10-22: not pulled to the centre here).
      const anchors = [];
      if (!closed) for (const [m, start] of [[members[0], true], [members.at(-1), false]]) {
        const vertex = start ? co[0] : co.at(-1);
        const local = (start === (m.sign === 1)) ? 0 : m.len;
        const explicitCentre = m.f.properties.jc && m.profile && !m.f.properties.goff && !m.f.properties.sh
          && (Math.abs(value(m.profile, local)) < 1e-9 || m.profile.jn?.[local === 0 ? 0 : 1]);
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
      // a chain end no other part of the line meets (a dead end)
      const dead = closed ? [false, false] : [co[0], co.at(-1)].map(v => ports.get(members[0].key + endpoint(v)).length === 1);
      chains.push({ co, members, distances, points, normals, ramps: joinedRamps, anchors, closed, len: at, box, blocks, maxSeat, dead });
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
  // Below z13 a junction profile's held ports give way to the earlier common
  // centre port (op.lo): there seats are a few pixels apart and a held seat
  // folds round a junction's short corners. Blended over z12.5 to z13.5.
  let lowWeight = 0;
  const profileValue = (profile, d) => profile.lo && lowWeight > 0
    ? value(profile, d) * (1 - lowWeight) + value(profile.lo, d) * lowWeight : value(profile, d);
  const profileRamps = profile => !profile.lo || lowWeight <= 0 ? profile.ramps
    : lowWeight >= 1 ? profile.lo.ramps : [...profile.ramps, ...profile.lo.ramps];
  function offsetValues(chain, member, at, out, ramps = chain.ramps) {
    const p = member.f.properties;
    const local = member.sign === 1 ? at - member.start : member.end - at;
    let off = (p.off || 0) * member.sign, group = (p.goff || 0) * member.sign, shared = p.sh || 0;
    if (member.profile) off = profileValue(member.profile, local) * member.sign;
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
          // A contracted loop leaves its crossing as a doubled vertex; meeting
          // there again end to end is no new loop (it used up the passes).
          if(lowWeight<1 && t>1-1e-9 && u<1e-9 && j===i+2 && points[i+1][0]===points[i+2][0] && points[i+1][1]===points[i+2][1]) continue;
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
  // A seat held round a curve tighter than its offset, or a seat ramp on such
  // a curve, runs the display backwards against its own source for a moment:
  // a loop, or a Z-shaped fold without a crossing (2026-10-22, Karlsruhe
  // Mühlburger Tor, Düsseldorf 706). Cut each backward run where the display
  // before it and after it are level along the source, within the seat's own
  // displacement; real source turnbacks stay. co, parameters in chain order.
  function unfold(co, parameters, chain, bound, ends = [false, false]) {
    if (co.length < 3) return;
    const tangent = at => {
      let i = Math.min(Math.max(lowerBound(chain.distances, at), 1), chain.points.length - 1);
      while (i < chain.points.length - 1 && chain.distances[i] === chain.distances[i - 1]) i++;
      const a = chain.points[i - 1], b = chain.points[i], dx = b[0] - a[0], dy = b[1] - a[1], n = Math.hypot(dx, dy);
      return n ? [dx / n, dy / n] : null;
    };
    const turnback = (lo, hi) => {
      for (let i = Math.max(1, lowerBound(chain.distances, lo)); i < chain.points.length - 1 && chain.distances[i] <= hi; i++) {
        const a = chain.points[i - 1], b = chain.points[i], c = chain.points[i + 1];
        const u = [b[0] - a[0], b[1] - a[1]], v = [c[0] - b[0], c[1] - b[1]], den = Math.hypot(...u) * Math.hypot(...v);
        if (den && (u[0] * v[0] + u[1] * v[1]) / den < -.5) return true;
      }
      return false;
    };
    const back = k => {
      const t = tangent((parameters[k] + parameters[k + 1]) / 2);
      const p = mercator(co[k]), q = mercator(co[k + 1]), s = [q[0] - p[0], q[1] - p[1]], n = Math.hypot(...s);
      return !!t && n > 1e-12 && (s[0] * t[0] + s[1] * t[1]) / n < -.05;
    };
    for (let pass = 0, k = 0; pass < 64 && k + 1 < co.length; ) {
      if (!back(k)) { k++; continue; }
      let j = k;
      while (j + 2 < co.length && back(j + 1)) j++;
      const p = co.map(mercator), A = p[k], B = p[j + 1];
      const t0 = tangent((parameters[k] + parameters[j + 1]) / 2);
      const f = P => (P[0] - A[0]) * t0[0] + (P[1] - A[1]) * t0[1], fB = f(B);
      let a = k, b = j + 1;
      while (a > 0 && f(p[a]) > fB && Math.hypot(p[a][0] - A[0], p[a][1] - A[1]) <= bound) a--;
      while (b < p.length - 1 && f(p[b]) < 0 && Math.hypot(p[b][0] - B[0], p[b][1] - B[1]) <= bound) b++;
      const cut = (i, level) => {
        const fi = f(p[i]), fj = f(p[i + 1]), t = fj === fi ? 0 : Math.max(0, Math.min(1, (level - fi) / (fj - fi)));
        return [[p[i][0] + (p[i + 1][0] - p[i][0]) * t, p[i][1] + (p[i + 1][1] - p[i][1]) * t],
          parameters[i] + (parameters[i + 1] - parameters[i]) * t];
      };
      const side = (P, Q) => Math.abs((P[0] - Q[0]) * t0[1] - (P[1] - Q[1]) * t0[0]);
      if (f(p[a]) > fB && a === 0 && f(p[b]) >= 0 && ends[0]) {
        // the fold starts the line (a branch's first corner): keep its first
        // point and go on from there no steeper than the side step it makes
        b = j + 1;
        while (b < p.length - 1 && f(p[b]) < side(p[b], p[0]) && Math.hypot(p[b][0] - p[0][0], p[b][1] - p[0][1]) <= 2 * bound) b++;
        if (f(p[b]) < side(p[b], p[0]) || turnback(parameters[0], parameters[b])) { k = j + 1; continue; }
        co.splice(1, b - 1); parameters.splice(1, b - 1);
        pass++; k = 0; continue;
      } else if (f(p[b]) < 0 && b === p.length - 1 && f(p[a]) <= fB && ends[1]) {
        const last = p.length - 1, fl = f(p[last]);
        a = k;
        while (a > 0 && fl - f(p[a]) < side(p[a], p[last]) && Math.hypot(p[a][0] - p[last][0], p[a][1] - p[last][1]) <= 2 * bound) a--;
        if (fl - f(p[a]) < side(p[a], p[last]) || turnback(parameters[a], parameters[last])) { k = j + 1; continue; }
        co.splice(a + 1, last - a - 1); parameters.splice(a + 1, last - a - 1);
        pass++; k = Math.max(0, a - 1); continue;
      }
      if (f(p[a]) > fB || f(p[b]) < 0 || turnback(parameters[a], parameters[b])) { k = j + 1; continue; }
      const [pa, ta] = cut(a, fB), [pb, tb] = cut(b - 1, 0);
      // the dropped stretch must stay within the seat's displacement of the cut
      const dx = pb[0] - pa[0], dy = pb[1] - pa[1], len2 = dx * dx + dy * dy;
      const far = p.slice(a + 1, b).some(P => {
        const t = len2 ? Math.max(0, Math.min(1, ((P[0] - pa[0]) * dx + (P[1] - pa[1]) * dy) / len2)) : 0;
        return Math.hypot(P[0] - pa[0] - t * dx, P[1] - pa[1] - t * dy) > bound;
      });
      if (far || tb < ta) { k = j + 1; continue; }
      co.splice(a + 1, b - a - 1, lnglat(pa), lnglat(pb));
      parameters.splice(a + 1, b - a - 1, ta, tb);
      pass++; k = Math.max(0, a);
    }
  }
  // A: display ending at a joint, B: display starting there (both in chain
  // order). The first crossing of A's last stretch within bound of the joint
  // with B's first stretch within bound: A ends and B starts at it.
  function trimJoint(A, B, bound) {
    if (A.length < 2 || B.length < 2) return null;
    const pa = A.map(mercator), pb = B.map(mercator), joint = pa.at(-1);
    let ia = pa.length - 1, ib = 0;
    while (ia > 0 && Math.hypot(pa[ia - 1][0] - joint[0], pa[ia - 1][1] - joint[1]) <= bound) ia--;
    while (ib < pb.length - 1 && Math.hypot(pb[ib + 1][0] - joint[0], pb[ib + 1][1] - joint[1]) <= bound) ib++;
    const cross = (p, q, r, t) => {
      const u = [q[0] - p[0], q[1] - p[1]], v = [t[0] - r[0], t[1] - r[1]], w = [r[0] - p[0], r[1] - p[1]];
      const den = u[0] * v[1] - u[1] * v[0];
      if (!den) return null;
      const s1 = (w[0] * v[1] - w[1] * v[0]) / den, s2 = (w[0] * u[1] - w[1] * u[0]) / den;
      return s1 > 1e-9 && s1 < 1 - 1e-9 && s2 > 1e-9 && s2 < 1 - 1e-9 ? [p[0] + s1 * u[0], p[1] + s1 * u[1]] : null;
    };
    for (let i = Math.max(0, ia - 1); i < pa.length - 1; i++) {
      for (let j = Math.min(ib, pb.length - 2); j >= 0; j--) {
        const x = cross(pa[i], pa[i + 1], pb[j], pb[j + 1]);
        if (!x) continue;
        const point = lnglat(x);
        return [[...A.slice(0, i + 1), point], [point, ...B.slice(j + 1)]];
      }
    }
    return null;
  }
  function render(chains, zoom, mode, bounds = null, selected = null) {
    lowWeight = 1 - smooth(zoom - 12.5);
    const features = [], world = 512 * 2 ** zoom;
    const atPorts = new Map(), branches = [], meets = new Map(), ofLine = new Map(), deadEnds = [];
    for (const chain of chains) {
      const pieces = [];
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
        if (Math.abs(profileValue(member.profile, local)) > 1e-9) continue;
        let other = index + (begin ? 1 : -1);
        while (other >= member.first && other <= member.last &&
          Math.hypot(chain.points[other][0]-chain.points[index][0],chain.points[other][1]-chain.points[index][1]) < 1e-15)
          other += begin ? 1 : -1;
        if (other < member.first || other > member.last) continue;
        const a = chain.points[begin ? index : other], b = chain.points[begin ? other : index];
        const dx=b[0]-a[0],dy=b[1]-a[1],length=Math.hypot(dx,dy);
        portNormals.set(index,[-dy/length,dx/length]);
      }
      // A branch leaves its trunk at the trunk's seat: its end normal is the
      // miter of the trunk and the branch, as if the chain came from the trunk,
      // so the branch starts on the offset line the trunk runs along.
      if (member.f.properties.jc && member.profile?.jn) for (const begin of [true, false]) {
        const index = begin ? member.first : member.last;
        if (index !== 0 && index !== chain.co.length - 1) continue;
        const trunk = member.profile.jn[(begin === (member.sign === 1)) ? 0 : 1]?.t;
        if (!trunk) continue;
        let other = index + (begin ? 1 : -1);
        while (other > member.first && other < member.last &&
          Math.hypot(chain.points[other][0]-chain.points[index][0],chain.points[other][1]-chain.points[index][1]) < 1e-15)
          other += begin ? 1 : -1;
        const unit = (p, q) => { const dx = q[0] - p[0], dy = q[1] - p[1], n = Math.hypot(dx, dy) || 1; return [dx / n, dy / n]; };
        const node = chain.points[index], out = unit(node, chain.points[other]), into = unit(mercator(trunk), node);
        const a = begin ? into : [-out[0], -out[1]], b = begin ? out : [-into[0], -into[1]];
        const x = a[0] + b[0], y = a[1] + b[1], den = 1 + a[0] * b[0] + a[1] * b[1];
        const scale = den > .5 ? 1 / den : 1 / Math.max(Math.hypot(x, y), 1e-12);
        portNormals.set(index, [-y * scale, x * scale]);
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
      if (member.profile) for (const [lo, hi] of profileRamps(member.profile)) for (const d of [lo, hi]) {
        for (const at of member.profile.period ? [d, d - member.profile.period] : [d]) {
          const local = (at - member.profile.origin) / member.profile.direction;
          const pos = member.sign === 1 ? member.start + local : member.end - local;
          if (pos > start && pos < end) positions.push(pos);
        }
      }
      if (member.profile) for (const [lo, hi] of profileRamps(member.profile)) {
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
      let display = co, at = null;
      if (member.f.properties.jc) {
        if (lowWeight < 1) unfold(co, parameters, chain, 2.5 * (chain.maxSeat + 1) * pixels({ off: 1, goff: 0, sh: 0, jk }, zoom, mode) / world,
          [!chain.closed && start <= 1e-12, !chain.closed && end >= chain.len - 1e-12]);
        const turnbacks=parameters.map(at=>{
          const i=lowerBound(chain.distances,at);
          if (!i || i>=chain.points.length-1 || Math.abs(chain.distances[i]-at)>1e-12) return false;
          const a=chain.points[i-1],b=chain.points[i],c=chain.points[i+1];
          const u=[b[0]-a[0],b[1]-a[1]],v=[c[0]-b[0],c[1]-b[1]],den=Math.hypot(...u)*Math.hypot(...v);
          return !den || (u[0]*v[0]+u[1]*v[1])/den<-.8;
        });
        const rounded = roundDisplay(co, zoom, parameters, turnbacks, !!member.f.properties.cl);
        display = rounded.co; at = rounded.at;
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
      pieces.push({ f, p, member, display, at, start, end, joint: !selected && !!member.f.properties.jc });
      }
      }
      // Two members of a chain meet at a junction node. Where a held seat
      // runs round a curve tighter than its offset there, the two offset
      // curves cross each other just before and after the node (a small
      // swallowtail split between two features). Cut both at that crossing,
      // within the seat's own displacement of the node, as roundDisplay does
      // for a loop inside one feature.
      const stepPx = pixels({ off: 1, goff: 0, sh: 0, jk: chain.members[0].f.properties.jk }, zoom, mode);
      const bound = 2.5 * (chain.maxSeat + 1) * stepPx / world;
      // A fold across the joint of two members (a seat held round the node's
      // corner, its miter point beyond the node): unfold the two as one line
      // and split them again at the joint.
      if (lowWeight < 1) for (let k = 0; k + 1 < pieces.length; k++) {
        const a = pieces[k], b = pieces[k + 1], joint = a.member.end;
        if (!a.joint || !b.joint || !a.at || !b.at || a.member === b.member || Math.abs(a.end - a.member.end) > 1e-12
          || Math.abs(b.start - b.member.start) > 1e-12 || Math.abs(joint - b.member.start) > 1e-12) continue;
        const co = [...a.display, ...b.display.slice(1)], parameters = [...a.at, ...b.at.slice(1)];
        if (parameters.some((t, i) => i && t < parameters[i - 1])) continue;
        const length = co.length;
        unfold(co, parameters, chain, bound);
        if (co.length === length) continue;
        let i = lowerBound(parameters, joint);
        let point;
        if (i < parameters.length && parameters[i] === joint) point = co[i];
        else if (i > 0 && i < parameters.length) {
          const t = (joint - parameters[i - 1]) / (parameters[i] - parameters[i - 1]), u = mercator(co[i - 1]), v = mercator(co[i]);
          point = lnglat([u[0] + (v[0] - u[0]) * t, u[1] + (v[1] - u[1]) * t]);
        } else continue;
        const before = co.slice(0, i).concat([point]), after = [point].concat(co.slice(parameters[i] === joint ? i + 1 : i));
        const atBefore = parameters.slice(0, i).concat([joint]), atAfter = [joint].concat(parameters.slice(parameters[i] === joint ? i + 1 : i));
        if (before.length < 2 || after.length < 2) continue;
        a.display = before; a.at = atBefore; b.display = after; b.at = atAfter;
      }
      for (let k = 0; k + 1 < pieces.length; k++) {
        const a = pieces[k], b = pieces[k + 1];
        const held = (m, atEnd) => m.profile?.jn?.[(atEnd === (m.sign === 1)) ? 1 : 0];
        if (lowWeight >= 1 || !a.joint || !b.joint || !(held(a.member, true) || held(b.member, false))
          || a.member === b.member || Math.abs(a.end - a.member.end) > 1e-12
          || Math.abs(b.start - b.member.start) > 1e-12 || Math.abs(a.member.end - b.member.start) > 1e-12) continue;
        const cut = trimJoint(a.display, b.display, bound);
        if (cut) [a.display, b.display] = cut;
      }
      for (const { f, p, member, display, start, end, joint } of pieces) {
        const feature = { ...f, properties: p, geometry: { type: 'LineString', coordinates: member.sign === 1 ? display : display.reverse() } };
        features.push(feature);
        if (joint && lowWeight < 1) {
          (ofLine.get(member.key) || ofLine.set(member.key, []).get(member.key)).push(feature);
          for (const [featureEnd, chainEnd] of [[0, member.sign === 1 ? 0 : 1], [-1, member.sign === 1 ? 1 : 0]]) {
            const at = chainEnd === 0 ? start : end;
            if (chain.dead[chainEnd] && Math.abs(at - (chainEnd === 0 ? 0 : chain.len)) < 1e-12)
              deadEnds.push({ feature, featureEnd, key: member.key, bound: (chain.maxSeat + 2) * pixels({ off: 1, goff: 0, sh: 0, jk: member.f.properties.jk }, zoom, mode) / world });
          }
        }
        if (joint && lowWeight < 1) for (const [featureEnd, covered] of [[0, member.sign === 1 ? start === member.start : end === member.end],
          [-1, member.sign === 1 ? end === member.end : start === member.start]]) {
          if (!covered) continue;
          const port = member.key + endpoint(member.coords.at(featureEnd));
          if (!meets.has(port)) meets.set(port, []);
          meets.get(port).push({ feature, featureEnd, bound: (chain.maxSeat + 2) * pixels({ off: 1, goff: 0, sh: 0, jk: member.f.properties.jk }, zoom, mode) / world });
        }
        if (!joint || !member.profile?.jn) continue;
        for (const [featureEnd, covered] of [[0, member.sign === 1 ? start === member.start : end === member.end],
          [-1, member.sign === 1 ? end === member.end : start === member.start]]) {
          const join = member.profile.jn[featureEnd === 0 ? 0 : 1];
          if (!covered || !join) continue;
          const port = member.key + endpoint(member.coords.at(featureEnd));
          if (!atPorts.has(port)) atPorts.set(port, []);
          atPorts.get(port).push({ feature, featureEnd, join });
          if (join.t) branches.push({ feature, featureEnd, port, bound: (chain.maxSeat + 2) * pixels({ off: 1, goff: 0, sh: 0, jk: member.f.properties.jk }, zoom, mode) / world });
        }
      }
    }
    // A branch starts on its trunk's offset line, at the trunk's miter corner;
    // where it turns towards the trunk's side that corner lies just before the
    // node and the branch's first stretch crosses the spine's strand. Start the
    // branch where the spine's strands meet at the node instead, cutting its
    // first stretch up to that crossing (within its seat's displacement).
    if (lowWeight < 1) for (const { feature, featureEnd, port, bound } of branches) {
      const own = feature.geometry.coordinates, head = featureEnd === 0 ? own : [...own].reverse();
      const ph = head.map(mercator), origin = ph[0];
      let best = null;
      for (const spine of atPorts.get(port) || []) {
        if (!spine.join.s) continue;
        const other = spine.feature.geometry.coordinates;
        const tail = (spine.featureEnd === 0 ? other : [...other].reverse()).map(mercator);
        let last = 1;
        while (last < tail.length - 1 && Math.hypot(tail[last][0] - origin[0], tail[last][1] - origin[1]) <= 2 * bound) last++;
        for (let i = 0; i + 1 < ph.length && Math.hypot(ph[i][0] - origin[0], ph[i][1] - origin[1]) <= bound; i++) {
          if (best && i > best.i) break;
          for (let j = 0; j < last; j++) {
            const u = [ph[i + 1][0] - ph[i][0], ph[i + 1][1] - ph[i][1]], v = [tail[j + 1][0] - tail[j][0], tail[j + 1][1] - tail[j][1]];
            const w = [tail[j][0] - ph[i][0], tail[j][1] - ph[i][1]], den = u[0] * v[1] - u[1] * v[0];
            if (!den) continue;
            const a = (w[0] * v[1] - w[1] * v[0]) / den, b = (w[0] * u[1] - w[1] * u[0]) / den;
            if (a > 1e-9 && a <= 1 && b >= 0 && b <= 1 && (!best || i < best.i || i === best.i && a < best.a))
              best = { i, a, joint: spine.featureEnd === 0 ? other[0] : other.at(-1) };
          }
        }
      }
      if (!best) continue;
      // from the spine's own end point at the node, so the line's parts meet in one point
      const cut = [[...best.joint], ...head.slice(best.i + 1)];
      feature.geometry = { type: 'LineString', coordinates: featureEnd === 0 ? cut : cut.reverse() };
    }
    // Any two pieces of one line that meet at a node meet there, they do not
    // cross: a piece ending on its own seat beyond the strand of the same line
    // it joins (a stub over the strand: Halle Tram 4, Düsseldorf 706, Bremen
    // Tram 1). Where the two heads cross within their seats' displacement of
    // the node, both end at the crossing.
    if (lowWeight < 1) for (const entries of meets.values()) {
      if (entries.length < 2) continue;
      const headOf = e => { const co = e.feature.geometry.coordinates; return e.featureEnd === 0 ? co : [...co].reverse(); };
      // a piece whose end another piece here shares runs on through the node: it stays whole
      const through = entries.map(e => entries.some(o => o !== e && o.feature !== e.feature
        && Math.hypot(...[0, 1].map(k => mercator(headOf(e)[0])[k] - mercator(headOf(o)[0])[k])) * world < 1e-6));
      for (let x = 0; x < entries.length; x++) for (let y = x + 1; y < entries.length; y++) {
        const A = entries[x], B = entries[y];
        if (A.feature === B.feature || through[x] && through[y]) continue;
        const ha = headOf(A), hb = headOf(B), pa = ha.map(mercator), pb = hb.map(mercator);
        if (pa.length < 2 || pb.length < 2) continue;
        const bound = Math.max(A.bound, B.bound), oa = pa[0], ob = pb[0];
        let best = null;
        for (let i = 0; i + 1 < pa.length && Math.hypot(pa[i][0] - oa[0], pa[i][1] - oa[1]) <= bound && !best; i++) {
          for (let j = 0; j + 1 < pb.length && Math.hypot(pb[j][0] - ob[0], pb[j][1] - ob[1]) <= bound; j++) {
            const u = [pa[i + 1][0] - pa[i][0], pa[i + 1][1] - pa[i][1]], v = [pb[j + 1][0] - pb[j][0], pb[j + 1][1] - pb[j][1]];
            const w = [pb[j][0] - pa[i][0], pb[j][1] - pa[i][1]], den = u[0] * v[1] - u[1] * v[0];
            if (!den) continue;
            const s = (w[0] * v[1] - w[1] * v[0]) / den, t = (w[0] * u[1] - w[1] * u[0]) / den;
            if (s > 1e-9 && s < 1 - 1e-9 && t > 1e-9 && t < 1 - 1e-9) { best = { i, j, point: lnglat([pa[i][0] + s * u[0], pa[i][1] + s * u[1]]) }; break; }
          }
        }
        if (!best) continue;
        const na = [best.point, ...ha.slice(best.i + 1)], nb = [best.point, ...hb.slice(best.j + 1)];
        if (na.length < 2 || nb.length < 2) continue;
        if (!through[x]) A.feature.geometry = { type: 'LineString', coordinates: A.featureEnd === 0 ? na : na.reverse() };
        if (!through[y]) B.feature.geometry = { type: 'LineString', coordinates: B.featureEnd === 0 ? nb : nb.reverse() };
      }
    }
    // A dead end of a line drawn across another stretch of the same line (its
    // source end just short of that stretch, the stretch's seat beyond it:
    // Halle Tram 4, Düsseldorf 706, Bremen Tram 1) ends where it meets it.
    if (lowWeight < 1) for (const { feature, featureEnd, key, bound } of deadEnds) {
      const own = feature.geometry.coordinates, head = featureEnd === 0 ? own : [...own].reverse();
      const ph = head.map(mercator), origin = ph[0];
      let best = null;
      for (const other of ofLine.get(key) || []) {
        if (other === feature) continue;
        const po = other.geometry.coordinates.map(mercator);
        for (let i = 0; i + 1 < ph.length && Math.hypot(ph[i][0] - origin[0], ph[i][1] - origin[1]) <= bound; i++) {
          if (best && i > best.i) break;
          for (let j = 0; j + 1 < po.length; j++) {
            const u = [ph[i + 1][0] - ph[i][0], ph[i + 1][1] - ph[i][1]], v = [po[j + 1][0] - po[j][0], po[j + 1][1] - po[j][1]];
            const w = [po[j][0] - ph[i][0], po[j][1] - ph[i][1]], den = u[0] * v[1] - u[1] * v[0];
            if (!den) continue;
            const a = (w[0] * v[1] - w[1] * v[0]) / den, b = (w[0] * u[1] - w[1] * u[0]) / den;
            if (a > 1e-9 && a < 1 - 1e-9 && b >= 0 && b <= 1 && (!best || i < best.i || i === best.i && a < best.a))
              best = { i, a, point: lnglat([ph[i][0] + a * u[0], ph[i][1] + a * u[1]]) };
          }
        }
      }
      if (!best) continue;
      const cut = [best.point, ...head.slice(best.i + 1)];
      if (cut.length < 2) continue;
      feature.geometry = { type: 'LineString', coordinates: featureEnd === 0 ? cut : cut.reverse() };
    }
    return { type: 'FeatureCollection', features };
  }
  return { smooth, value, parse, prepare, properties, pixels, render, renderStrokes, bindStroke, mercator, identity, roundDisplay };
})();
