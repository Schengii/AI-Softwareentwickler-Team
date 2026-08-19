import { IsString, IsNotEmpty, MinLength } from 'class-validator';

export class CreateJobCommand {
  @IsString() @IsNotEmpty() @MinLength(5)
  public readonly title: string;

  @IsString() @IsNotEmpty()
  public readonly description: string;

  @IsString() @IsNotEmpty()
  public readonly companyId: string;

  constructor(data: CreateJobCommand) {
    Object.assign(this, data);
  }
}
