import argparse
import os

#
#  Arguments are:
#     start_bucket      : starting bucket of first train within the pattern
#     bunch_spacing     : buckets between buckets within the train
#     bunches_per_train : bunches within each train 
#     trains_per_second : number of trains within the pattern
#     train_spacing     : buckets from last bunch of previous train to
#                         first bunch of the next train
#     repeat            : repeat pattern or run only once
#
class TrainGenerator(object):
    def __init__(self, start_bucket=0, 
                 train_spacing=910000, trains_per_second=1, 
                 bunch_spacing=1, bunches_per_train=1, 
                 charge=0, repeat=False):
        self.start_bucket      = start_bucket
        self.train_spacing     = train_spacing
        self.trains_per_second = trains_per_second
        self.bunch_spacing     = bunch_spacing
        self.bunches_per_train = bunches_per_train
        self.charge            = charge
        self.repeat            = repeat
        self.async_start       = None if repeat else 0

        print(vars(self))

        self.instr = ['instrset = []']
        self._fill_instr()

    def _train(self, cc):
        intb = self.bunch_spacing
        nb   = self.bunches_per_train
        w    = 0
        self.instr.append('#   {} bunches / _train'.format(nb))
        self.instr.append('instrset.append(BeamRequest({}))'.format(self.charge))
        rb = nb-1
        if rb:
            if rb > 0xfff:
                self.instr.append('iinstr=len(instrset)')
                self._wait(intb)
                self.instr.append('instrset.append(BeamRequest({}))'.format(self.charge))
                self.instr.append('instrset.append(Branch.conditional(line=iinstr,counter={},value={}))'.format(cc[1],(rb//0x1000) -1))
                rb = rb & 0xfff

            if rb:
                self.instr.append('iinstr=len(instrset)')
                self._wait(intb)
                self.instr.append('instrset.append(BeamRequest({}))'.format(self.charge))
                if rb > 1:
                    self.instr.append('instrset.append(Branch.conditional(line=iinstr,counter={},value={}))'.format(cc[0],rb-1))
            w = intb*(nb-1)
        return w

    def _wait(self, intv):
        if intv <= 0:
            raise ValueError
        if intv >= 0xfff:
            self.instr.append('iinstr = len(instrset)')
            #  _Wait for 4095 intervals
            self.instr.append('instrset.append( FixedRateSync(marker=0, occ=4095) )')
            if intv >= 0x1ffe:
                #  Branch conditionally to previous instruction
                self.instr.append('instrset.append( Branch.conditional(line=iinstr, counter=3, value={}) )'.format(int(intv/0xfff)-1))

        rint = intv%0xfff
        if rint:
            self.instr.append('instrset.append( FixedRateSync(marker=0, occ={} ) )'.format(rint))

    def _fill_instr(self):
        #  How many times to repeat beam requests in "1 second"
        #  nint = 910000/intv
        #  Global sync counts as 1 cycle
        nint = self.trains_per_second
        intv = self.train_spacing
        if nint==0:
            nint = 910000/intv

        if nint>1:
            print('Generating {} _trains with {} _train spacing'.
                  format(nint,intv))
        if self.bunches_per_train>1: 
            print('\tcontaining {} bunches with {} spacing'.
                  format(self.bunches_per_train,
                         self.bunch_spacing))

        #  Initial validation
        if ((nint-1)*intv+(self.bunches_per_train-1)*self.bunch_spacing) >= 910000:
            raise ValueError

        if self.start_bucket>0:
            self.instr.append('# start at bucket {}'.format(self.start_bucket))
            self._wait(self.start_bucket)

        rint = nint % 256
        if rint:
            self.instr.append('# loop A: {} _trains'.format(rint))
            self.instr.append('startreq = len(instrset)')
            self._wait(intv-self._train([1,2]))
            if rint > 1:
                self.instr.append('instrset.append( Branch.conditional(startreq, 0, {}) )'.format(rint-1))
            self.instr.append('# end loop A')
            nint = nint - rint

        rint = (nint/256) % 256
        if rint:
            self.instr.append('# loop B: {} _trains'.format(rint*256))
            self.instr.append('startreq = len(instrset)')
            self._wait(intv-self._train([1]))  # don't need 2 counters because trains_per_bunch>4096 can't have trains_per_second>256
            self.instr.append('instrset.append( Branch.conditional(startreq, 0, 255) )')
            if rint > 1:
                self.instr.append('instrset.append( Branch.conditional(startreq, 2, {}) )'.format(rint-1))
            self.instr.append('# end loop B')
            nint = nint - rint*256

        rint = (nint / (256*256)) % 256
        if rint:
            self.instr.append('# loop C: {} _trains'.format(rint*256*256))
            self.instr.append('# loop (n_trains / 256)')
            self.instr.append('startreq = len(instrset)')
            self._wait(intv-self._train([3]))  # can use counter 3 here because no delay can be greater than 4096 (actually 3554)
            self.instr.append('instrset.append( Branch.conditional(startreq, 0, 255) )')
            self.instr.append('instrset.append( Branch.conditional(startreq, 1, 255) )')
            if rint > 1:
                self.instr.append('instrset.append( Branch.conditional(startreq, 2, {}) )'.format(rint-1))
            self.instr.append('# end loop C')
            nint = nint - rint*256*256

        if self.repeat:
            #  Unconditional branch (opcode 2) to instruction 0 (1Hz sync)
            self.instr.append('instrset.append( Branch.unconditional(0) )')
        else:
            #  Unconditional branch to here
            self.instr.append('last = len(instrset)')
            self.instr.append('instrset.append( Branch.unconditional(last) )')


def main():
    parser = argparse.ArgumentParser(description='simple validation printing')
    parser.add_argument("-o", "--output"            , required=True , help="file output path")
    parser.add_argument("-t", "--train_spacing"     , required=True , type=int, help="buckets between start of each _train")
    parser.add_argument("-N", "--trains_per_second" , required=False, type=int, help="number of _trains per TPG second", default=0)
    parser.add_argument("-b", "--bunch_spacing"     , required=True , type=int, help="buckets between bunches within _train")
    parser.add_argument("-n", "--bunches_per_train" , required=True , type=int, help="number of bunches in each _train")
    parser.add_argument("-s", "--start_bucket"      , default=0     , type=int, help="starting bucket for first _train")
    parser.add_argument("-q", "--charge"            , default=0     , type=int, help="bunch charge, pC")
    parser.add_argument("-r", "--repeat"            , default=False , help="repeat sequence each second")
    args = parser.parse_args()
    TrainGenerator(args)

if __name__ == '__main__':
    main()
