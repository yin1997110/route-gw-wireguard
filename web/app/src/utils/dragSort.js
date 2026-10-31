// 职责: 表格行拖拽排序的通用挂载工具(HTML5 原生拖放，零依赖)。
// 只负责"算出起止位置并回调"，不直接改动 DOM —— 顺序变更由 store 提交后重新渲染，避免与 Vue 虚拟 DOM 冲突。
// EXTENSION_POINT: 其他需要拖拽排序的列表(节点分组、订阅源)可复用 enableRowDrag。

/**
 * @param {HTMLElement} root   包含 tr 行的容器(通常是 el-table 的 body-wrapper)
 * @param {object} opts
 * @param {(from:number,to:number)=>void} opts.onChange 拖放结束回调(索引基于当前渲染顺序)
 * @param {(el:HTMLElement)=>boolean} [opts.enable] 判定哪些行可拖(默认排除测量行)
 * @returns {() => void} dispose
 */
export function enableRowDrag(root, { onChange, enable }) {
  const rows = () => Array.from(root.querySelectorAll('tr')).filter((tr) => tr.querySelector('td'))
  let from = -1
  let to = -1

  function mark(list) {
    list.forEach((tr) => {
      if (!enable || enable(tr)) tr.draggable = true
    })
  }
  // Element Plus 重绘行后需要重新设置 draggable
  const observer = new MutationObserver(() => mark(rows()))
  observer.observe(root, { childList: true, subtree: true })
  mark(rows())

  function onDragStart(e) {
    const tr = e.target.closest('tr')
    if (!tr || tr.draggable !== true) return
    from = rows().indexOf(tr)
    if (from < 0) return
    tr.classList.add('gw-drag-ghost')
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('text/plain', String(from))
  }
  function onDragOver(e) {
    if (from < 0) return
    const tr = e.target.closest('tr')
    if (!tr) return
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
    const list = rows()
    const idx = list.indexOf(tr)
    if (idx < 0 || idx === from) return
    if (to >= 0 && to !== idx) list[to]?.classList.remove('gw-drag-chosen')
    to = idx
    tr.classList.add('gw-drag-chosen')
  }
  function clean() {
    const list = rows()
    list.forEach((tr) => tr.classList.remove('gw-drag-ghost', 'gw-drag-chosen'))
    from = -1
    to = -1
  }
  function onDragEnd() {
    if (from >= 0 && to >= 0 && from !== to) onChange(from, to)
    clean()
  }
  function onDrop(e) {
    e.preventDefault()
    onDragEnd()
  }

  root.addEventListener('dragstart', onDragStart)
  root.addEventListener('dragover', onDragOver)
  root.addEventListener('drop', onDrop)
  root.addEventListener('dragend', onDragEnd)

  return function dispose() {
    observer.disconnect()
    root.removeEventListener('dragstart', onDragStart)
    root.removeEventListener('dragover', onDragOver)
    root.removeEventListener('drop', onDrop)
    root.removeEventListener('dragend', onDragEnd)
  }
}
