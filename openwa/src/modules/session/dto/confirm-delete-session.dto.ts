import { Type } from 'class-transformer';
import { IsInt, Min } from 'class-validator';
import { ApiProperty } from '@nestjs/swagger';

export class ConfirmDeleteSessionDto {
  @ApiProperty({ description: 'Exact message count returned by GET /sessions/:id/delete-impact', minimum: 0 })
  @Type(() => Number)
  @IsInt()
  @Min(0)
  confirmMessageCount!: number;
}
