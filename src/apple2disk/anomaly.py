import sys

class AnomalyLevel(object):
    def __init__(self, level):
        self.level = level

    def __str__(self):
        return level

module = sys.modules[__name__]
for level in ['INFO', 'UNUSUAL', 'CORRUPTION']:
    setattr(module, level, AnomalyLevel(level))


class Anomaly(object):
    def __init__(self, container, level, details):
        """Record of an anomaly found during disk processing.
        
        Args:
            container: object that contains the anomaly
            level: AnomalyLevel
            details: string description of anomaly (str)
        """
        self.container = container
        self.level = level
        self.details = details

    def __str__(self):
        return '%s anomaly in %s: %s' % (self.level, self.container, self.details)