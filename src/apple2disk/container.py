class Container(object):
    """Generic container type, every structure on the disk extends from this."""

    def __init__(self):
        self.anomalies = []

        self.parent = None
        self.children = []

    def AddChild(self, child):
        assert child.parent is None, "%s already has parent %s" % (child, child.parent)

        self.children.append(child)
        child.parent = self

    def Recurse(self, callback):
        """Depth-first recursive traversal of children."""
        for child in self.children:
            callback(child)
            child.Recurse(callback)
