import { Injectable } from '@angular/core';

/** Thin fetch wrapper for the local API. Errors carry the server's message. */
@Injectable({ providedIn: 'root' })
export class Api {
  async request<T>(method: string, path: string, body?: unknown, file?: Blob): Promise<T> {
    const headers: Record<string, string> = {};
    if (file) headers['Content-Type'] = 'application/octet-stream';
    else if (body !== undefined) headers['Content-Type'] = 'application/json';
    const res = await fetch(`/api${path}`, {
      method,
      headers,
      body: file ?? (body !== undefined ? JSON.stringify(body) : undefined),
    });
    if (!res.ok) throw new Error(await errorText(res));
    if (res.status === 204) return undefined as T;
    return res.json() as Promise<T>;
  }

  get<T>(path: string): Promise<T> {
    return this.request<T>('GET', path);
  }
  put<T>(path: string, body: unknown): Promise<T> {
    return this.request<T>('PUT', path, body);
  }
  post<T>(path: string, body: unknown = {}): Promise<T> {
    return this.request<T>('POST', path, body);
  }
  delete<T = void>(path: string): Promise<T> {
    return this.request<T>('DELETE', path);
  }
  upload<T>(path: string, file: File): Promise<T> {
    return this.request<T>('POST', `${path}?filename=${encodeURIComponent(file.name)}`, undefined, file);
  }
}

async function errorText(res: Response): Promise<string> {
  try {
    const data = await res.json();
    if (typeof data.detail === 'string') return data.detail;
    if (Array.isArray(data.detail)) {
      // FastAPI validation errors: "filters.salary_floor: Input should be a valid integer"
      return data.detail.map((d: { loc: string[]; msg: string }) => `${d.loc.slice(1).join('.')}: ${d.msg}`).join('; ');
    }
  } catch {
    // not JSON
  }
  return `${res.status} ${res.statusText}`;
}
