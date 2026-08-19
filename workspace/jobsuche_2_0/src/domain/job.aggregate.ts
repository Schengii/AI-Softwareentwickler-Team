import { AggregateRoot } from '@nestjs/cqrs';
import { JobCreatedEvent } from '../events/job-created.event';

export class JobAggregate extends AggregateRoot {
  private id: string;
  private status: 'DRAFT' | 'PUBLISHED' = 'DRAFT';

  constructor(private readonly aggregateId: string) {
    super();
    this.id = aggregateId;
  }

  create(title: string, description: string, companyId: string) {
    if (!title || title.length < 5) throw new Error('Invalid Title');
    
    this.apply(new JobCreatedEvent(this.id, title, description, companyId));
  }
}
