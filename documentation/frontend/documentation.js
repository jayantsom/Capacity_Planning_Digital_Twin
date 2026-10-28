import { apiJson } from '/shared/static/dashboard.js';

const navigation = document.getElementById('documentationNavigation');
const search = document.getElementById('documentationSearch');
const content = document.getElementById('markdownContent');
const title = document.getElementById('documentationTitle');
const pathLabel = document.getElementById('documentationPath');
const status = document.getElementById('documentationStatus');
let catalog = [];

function appendInline(parent, text) {
  const token = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\))/g;
  let offset = 0;
  text.replace(token, (match, _value, index) => {
    if (index > offset) parent.append(document.createTextNode(text.slice(offset, index)));
    if (match.startsWith('**')) {
      const strong = document.createElement('strong');
      strong.textContent = match.slice(2, -2);
      parent.append(strong);
    } else if (match.startsWith('`')) {
      const code = document.createElement('code');
      code.textContent = match.slice(1, -1);
      parent.append(code);
    } else {
      const parts = match.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
      const link = document.createElement('a');
      link.textContent = parts[1];
      link.href = parts[2];
      if (/^https?:\/\//.test(parts[2])) {
        link.target = '_blank';
        link.rel = 'noreferrer';
      }
      parent.append(link);
    }
    offset = index + match.length;
    return match;
  });
  if (offset < text.length) parent.append(document.createTextNode(text.slice(offset)));
}

function tableBlock(lines, start) {
  if (
    start + 1 >= lines.length
    || !lines[start].includes('|')
    || !/^\s*\|?[\s:|-]+\|[\s:|-]+/.test(lines[start + 1])
  ) return null;
  const rows = [];
  let index = start;
  while (index < lines.length && lines[index].includes('|') && lines[index].trim()) {
    if (index !== start + 1) {
      rows.push(lines[index].trim().replace(/^\||\|$/g, '').split('|').map((cell) => cell.trim()));
    }
    index += 1;
  }
  const table = document.createElement('table');
  const head = document.createElement('thead');
  const headRow = document.createElement('tr');
  rows.shift().forEach((cell) => {
    const header = document.createElement('th');
    appendInline(header, cell);
    headRow.append(header);
  });
  head.append(headRow);
  const body = document.createElement('tbody');
  rows.forEach((values) => {
    const row = document.createElement('tr');
    values.forEach((value) => {
      const cell = document.createElement('td');
      appendInline(cell, value);
      row.append(cell);
    });
    body.append(row);
  });
  table.append(head, body);
  return { node: table, next: index };
}

function normalizedHeading(value) {
  return String(value).trim().toLowerCase().replace(/\s+/g, ' ');
}

function renderMarkdown(markdown, pageTitle) {
  content.replaceChildren();
  const lines = markdown.replaceAll('\r\n', '\n').split('\n');
  let index = 0;
  let headingSeen = false;
  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
      continue;
    }
    if (line.startsWith('```')) {
      const language = line.slice(3).trim();
      const values = [];
      index += 1;
      while (index < lines.length && !lines[index].startsWith('```')) {
        values.push(lines[index]);
        index += 1;
      }
      const pre = document.createElement('pre');
      const code = document.createElement('code');
      code.dataset.language = language;
      code.textContent = values.join('\n');
      pre.append(code);
      content.append(pre);
      index += 1;
      continue;
    }
    const table = tableBlock(lines, index);
    if (table) {
      content.append(table.node);
      index = table.next;
      continue;
    }
    const heading = line.match(/^(#{1,6})\s+(.+)$/);
    if (heading) {
      const isFirstHeading = !headingSeen;
      headingSeen = true;
      if (
        isFirstHeading
        && normalizedHeading(heading[2]) === normalizedHeading(pageTitle)
      ) {
        index += 1;
        continue;
      }
      const node = document.createElement(`h${Math.min(6, heading[1].length + 1)}`);
      appendInline(node, heading[2]);
      node.id = heading[2].toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
      content.append(node);
      index += 1;
      continue;
    }
    if (/^\s*[-*]\s+/.test(line) || /^\s*\d+\.\s+/.test(line)) {
      const ordered = /^\s*\d+\./.test(line);
      const list = document.createElement(ordered ? 'ol' : 'ul');
      while (
        index < lines.length
        && (ordered ? /^\s*\d+\.\s+/.test(lines[index]) : /^\s*[-*]\s+/.test(lines[index]))
      ) {
        const item = document.createElement('li');
        appendInline(item, lines[index].replace(/^\s*(?:[-*]|\d+\.)\s+/, ''));
        list.append(item);
        index += 1;
      }
      content.append(list);
      continue;
    }
    if (line.startsWith('> ')) {
      const quote = document.createElement('blockquote');
      appendInline(quote, line.slice(2));
      content.append(quote);
      index += 1;
      continue;
    }
    const paragraphLines = [line.trim()];
    index += 1;
    while (
      index < lines.length
      && lines[index].trim()
      && !/^(#{1,6})\s+|^```|^\s*[-*]\s+|^\s*\d+\.\s+|^> /.test(lines[index])
      && !tableBlock(lines, index)
    ) {
      paragraphLines.push(lines[index].trim());
      index += 1;
    }
    const paragraph = document.createElement('p');
    appendInline(paragraph, paragraphLines.join(' '));
    content.append(paragraph);
  }
}

function renderNavigation(filter = '') {
  const normalized = filter.trim().toLowerCase();
  navigation.replaceChildren();
  catalog.forEach((group) => {
    const matches = group.pages.filter((page) => (
      !normalized || `${page.title} ${page.path}`.toLowerCase().includes(normalized)
    ));
    if (!matches.length) return;
    const section = document.createElement('section');
    const heading = document.createElement('h2');
    heading.textContent = group.title;
    section.append(heading);
    matches.forEach((page) => {
      const link = document.createElement('a');
      link.href = `#${page.slug}`;
      link.dataset.slug = page.slug;
      link.textContent = page.title;
      section.append(link);
    });
    navigation.append(section);
  });
}

async function loadPage(slug) {
  const payload = await apiJson(`/documentation/api/pages/${encodeURIComponent(slug)}`);
  title.textContent = payload.title;
  pathLabel.textContent = payload.path;
  renderMarkdown(payload.markdown, payload.title);
  navigation.querySelectorAll('[data-slug]').forEach((link) => {
    if (link.dataset.slug === slug) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });
  document.querySelector('.documentation-content').scrollTop = 0;
}

async function initialize() {
  try {
    const [health, payload] = await Promise.all([
      apiJson('/documentation/api/health'),
      apiJson('/documentation/api/catalog'),
    ]);
    status.textContent = health.status.toUpperCase();
    status.dataset.state = health.status === 'ready' ? 'ready' : 'warning';
    catalog = payload.groups;
    renderNavigation();
    const pages = catalog.flatMap((group) => group.pages);
    const requested = window.location.hash.slice(1);
    const first = pages.find((page) => page.slug === requested) || pages[0];
    if (first) {
      window.location.hash = first.slug;
      await loadPage(first.slug);
    }
  } catch (error) {
    status.textContent = 'DEGRADED';
    status.dataset.state = 'warning';
    content.textContent = error.message;
  }
}

search.addEventListener('input', () => renderNavigation(search.value));
window.addEventListener('hashchange', () => {
  const slug = window.location.hash.slice(1);
  if (slug) void loadPage(slug);
});

void initialize();
