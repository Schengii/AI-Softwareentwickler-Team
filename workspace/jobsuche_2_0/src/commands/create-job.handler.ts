import { CommandHandler, ICommandHandler, EventPublisher } from '@nestjs/cqrs';
import { CreateJobCommand } from './create-job.command';
import { JobAggregate } from '../domain/job.aggregate';
import { Injectable } from '@nestjs/common';
import { randomUUID } from 'crypto';

@Injectable()
@CommandHandler(CreateJobCommand)
export class CreateJobHandler implements ICommandHandler<CreateJobCommand> {
  constructor(private readonly publisher: EventPublisher) {}

  async execute(command: CreateJobCommand): Promise<void> {
    const { title, description, companyId } = command;
    
    // Aggregate Instanziierung mit Factory-Logik
    const job = this.publisher.mergeObjectContext(
      new JobAggregate(randomUUID())
    );

    job.create(title, description, companyId);
    job.commit(); // Persistiert Events via EventStore
  }
}
