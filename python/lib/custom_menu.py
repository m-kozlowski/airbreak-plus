"""Compile declarative menu placement without changing the on-device registry."""

from dataclasses import dataclass


@dataclass(frozen=True)
class StockRef:
    name: str


@dataclass(frozen=True)
class CustomRef:
    var: object


@dataclass(frozen=True)
class ItemRef:
    owner: object
    index: int


def stock(name):
    """Refer to a whole stock row by one of its UART variable names."""
    return StockRef(name.upper())


def custom(var):
    """Refer to a custom variable, including one registered later."""
    return CustomRef(var)


@dataclass(frozen=True)
class MenuDispatch:
    site: int
    before_first: int
    before_count: int
    after_first: int
    after_count: int


@dataclass
class MenuPlan:
    entries: list
    dispatch: list
    page_containers: dict


class MenuBuilder:
    PAGE = 4
    HEADING = 2
    PAGE_BASE = 0x80
    LIMIT = 64

    def __init__(self):
        self.entries = []
        self.placements = []

    def add(self, entry, *, before=None, after=None):
        if before is not None and after is not None:
            raise ValueError('custom menu: use either before or after, not both')
        target = before if before is not None else after
        if target is not None and not isinstance(target, (StockRef, CustomRef, ItemRef)):
            raise ValueError('custom menu: placement requires stock(), custom(), or an item handle')
        if len(self.entries) >= self.LIMIT:
            raise ValueError('custom menu: registry limit of %d entries exceeded' % self.LIMIT)
        handle = ItemRef(self, len(self.entries))
        self.entries.append(entry)
        self.placements.append((target, before is not None))
        return handle

    def compile(self, anchors, resolve_var):
        """anchors resolves (section, UART name or None for section end) to a site.

        Each item attaches to one stock row or another custom item in the same
        container. Children on either side retain declaration order; an item's
        children travel with it. All references are resolved before emitting.
        """
        variables = {}
        for i, (_, flags, item_id, _) in enumerate(self.entries):
            if not flags & (self.PAGE | self.HEADING):
                if item_id in variables:
                    raise ValueError('custom menu: duplicate variable 0x%04X' % item_id)
                variables[item_id] = i

        parents = []
        children = {}
        roots = {}
        for i, ((container, _, _, _), (target, before)) in enumerate(
                zip(self.entries, self.placements)):
            if isinstance(target, CustomRef):
                var_id = resolve_var(target.var)
                if var_id not in variables:
                    raise ValueError('custom menu: unregistered custom variable %s' % target.var)
                parent = variables[var_id]
            elif isinstance(target, ItemRef):
                if target.owner is not self or not 0 <= target.index < len(self.entries):
                    raise ValueError('custom menu: item handle belongs to another registry')
                parent = target.index
            else:
                parent = None

            if parent is not None:
                if self.entries[parent][0] != container:
                    raise ValueError('custom menu: placement reference crosses containers')
                children.setdefault((parent, before), []).append(i)
            else:
                if container >= self.PAGE_BASE:
                    if isinstance(target, StockRef):
                        raise ValueError('custom menu: generated pages have no stock anchors')
                    site = None
                else:
                    site = anchors(container, target.name if target else None)
                roots.setdefault((container, site, before), []).append(i)
            parents.append(parent)

        # Detect cycles even when the component has no root, before any emission.
        states = [0] * len(parents)
        def visit(i):
            if states[i] == 1:
                raise ValueError('custom menu: cycle in placement references')
            if states[i] == 2:
                return
            states[i] = 1
            if parents[i] is not None:
                visit(parents[i])
            states[i] = 2
        for i in range(len(parents)):
            visit(i)

        ordered = []
        def emit(i):
            for child in children.get((i, True), ()):
                emit(child)
            ordered.append(i)
            for child in children.get((i, False), ()):
                emit(child)

        dispatch = []
        for container in sorted({entry[0] for entry in self.entries}):
            sites = {site for c, site, _ in roots if c == container}
            for site in sorted(sites, key=lambda value: -1 if value is None else value):
                first = len(ordered)
                for i in roots.get((container, site, True), ()):
                    emit(i)
                middle = len(ordered)
                for i in roots.get((container, site, False), ()):
                    emit(i)
                if site is not None:
                    dispatch.append(MenuDispatch(site, first, middle-first,
                                                 middle, len(ordered)-middle))

        # PAGE records define runtime page ordinals. Reorder their containers
        # together with the records, including nested-page parent containers.
        old_pages = [i for i, entry in enumerate(self.entries) if entry[1] & self.PAGE]
        old_containers = {i: self.PAGE_BASE + n for n, i in enumerate(old_pages)}
        new_pages = [i for i in ordered if i in old_containers]
        remap = {old_containers[i]: self.PAGE_BASE + n for n, i in enumerate(new_pages)}
        entries = [(remap.get(c, c), flags, item, mask)
                   for c, flags, item, mask in (self.entries[i] for i in ordered)]
        return MenuPlan(entries, dispatch, remap)
