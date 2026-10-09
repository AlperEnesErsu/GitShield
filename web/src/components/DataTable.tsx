import { ReactNode, useMemo, useState } from "react";

export interface Column<T> {
  key: string;
  header: string;
  render: (row: T) => ReactNode;
  /** Value used for sorting; columns without it are not sortable. */
  sortValue?: (row: T) => string | number | null;
  align?: "left" | "right" | "center";
  width?: string;
  /** Hide on narrow screens. */
  secondary?: boolean;
}

interface Props<T> {
  rows: T[];
  columns: Column<T>[];
  rowKey: (row: T) => string | number;
  onRowClick?: (row: T) => void;
  initialSort?: { key: string; dir: "asc" | "desc" };
  empty?: ReactNode;
}

export function DataTable<T>({ rows, columns, rowKey, onRowClick, initialSort, empty }: Props<T>) {
  const [sort, setSort] = useState(initialSort);

  const sorted = useMemo(() => {
    const col = columns.find((c) => c.key === sort?.key);
    if (!col?.sortValue || !sort) return rows;
    const get = col.sortValue;
    const dir = sort.dir === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => {
      const va = get(a);
      const vb = get(b);
      if (va === vb) return 0;
      if (va === null) return 1;
      if (vb === null) return -1;
      return va < vb ? -dir : dir;
    });
  }, [rows, columns, sort]);

  const toggleSort = (col: Column<T>) => {
    if (!col.sortValue) return;
    setSort((s) =>
      s?.key === col.key
        ? { key: col.key, dir: s.dir === "asc" ? "desc" : "asc" }
        : { key: col.key, dir: "desc" },
    );
  };

  if (!rows.length) return <div className="empty">{empty ?? "Kayıt yok."}</div>;

  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            {columns.map((col) => (
              <th
                key={col.key}
                style={{ width: col.width, textAlign: col.align }}
                className={`${col.sortValue ? "sortable" : ""} ${col.secondary ? "secondary" : ""}`}
                onClick={() => toggleSort(col)}
                aria-sort={
                  sort?.key === col.key ? (sort.dir === "asc" ? "ascending" : "descending") : undefined
                }
              >
                {col.header}
                {sort?.key === col.key && <span className="sort-arrow">{sort.dir === "asc" ? "↑" : "↓"}</span>}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => (
            <tr
              key={rowKey(row)}
              className={onRowClick ? "clickable" : undefined}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
            >
              {columns.map((col) => (
                <td
                  key={col.key}
                  style={{ textAlign: col.align }}
                  className={col.secondary ? "secondary" : undefined}
                >
                  {col.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
