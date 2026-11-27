import { Pipe, PipeTransform } from '@angular/core';
import { apiSrc } from './net';

/** `[src]="url | apiSrc | async"`: API files (screenshots, CV PDFs) that also load on the phone, through the tunnel. */
@Pipe({ name: 'apiSrc' })
export class ApiSrcPipe implements PipeTransform {
  transform(url: string): Promise<string> {
    return apiSrc(url);
  }
}
