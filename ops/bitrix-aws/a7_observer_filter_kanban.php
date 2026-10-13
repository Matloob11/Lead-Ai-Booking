<?php
if (!class_exists(\Bitrix\Crm\Kanban\Entity\Lead::class, true)) {
    return;
}

class A7KanbanLead extends \Bitrix\Crm\Kanban\Entity\Lead
{
    public function prepareFilter(array &$filter, ?string $viewMode = null): void
    {
        parent::prepareFilter($filter, $viewMode);
        A7ObserverFilter::applyToCrmFilter($filter);
    }

    public function getItems(array $parameters): \CDBResult
    {
        if (isset($parameters['filter']) && is_array($parameters['filter'])) {
            A7ObserverFilter::applyToCrmFilter($parameters['filter']);
        }
        return parent::getItems($parameters);
    }

    public function fillStageTotalSums(array $filter, array $runtime, array &$stages): void
    {
        A7ObserverFilter::applyToCrmFilter($filter);
        parent::fillStageTotalSums($filter, $runtime, $stages);
    }
}
