import { IsOptional, IsIn } from 'class-validator';

export type StatsPeriod = '24h' | '7d' | '30d' | '1y';

export class StatsQueryDto {
  @IsOptional()
  @IsIn(['24h', '7d', '30d', '1y'])
  period?: StatsPeriod = '24h';
}
