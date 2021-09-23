class LogDictionary(dict):

    def __setitem__(self, k, v):
        super(LogDictionary, self).__setitem__(k, v)
        print('%s = %s' % (k, v))
