import umath
import Numeric as Num
import struct
import sys, psr_utils, infodata, polycos, Pgplot, sinc_interp, copy, random
from types import StringType, FloatType, IntType
from bestprof import bestprof
from scipy.io.numpyio import fread

class pfd:

    def __init__(self, filename):
        self.pfd_filename = filename
        infile = open(filename, "rb")
        # See if the .bestprof file is around
        try:
            self.bestprof = bestprof(filename+".bestprof")
        except IOError:
            self.bestprof = 0
        swapchar = '<' # this is little-endian
        data = infile.read(5*4)
        testswap = struct.unpack(swapchar+"i"*5, data)
        if min(umath.fabs(Num.asarray(testswap))) > 100000:
            swapchar = '>' # this is big-endian
        (self.numdms, self.numperiods, self.numpdots, self.nsub, self.npart) = \
                      struct.unpack(swapchar+"i"*5, data)
        (self.proflen, self.numchan, self.pstep, self.pdstep, self.dmstep, \
         self.ndmfact, self.npfact) = struct.unpack(swapchar+"i"*7, infile.read(7*4))
        self.filenm = infile.read(struct.unpack(swapchar+"i", infile.read(4))[0])
        self.candnm = infile.read(struct.unpack(swapchar+"i", infile.read(4))[0])
        self.telescope = infile.read(struct.unpack(swapchar+"i", infile.read(4))[0])
        self.pgdev = infile.read(struct.unpack(swapchar+"i", infile.read(4))[0])
        test = infile.read(16)
        has_posn = 1
        for ii in range(16):
            if test[ii] not in '0123456789:.-\0':
                has_posn = 0
                break
        if has_posn:
            self.rastr = test[:test.find('\0')]
            test = infile.read(16)
            self.decstr = test[:test.find('\0')]
            (self.dt, self.startT) = struct.unpack(swapchar+"dd", infile.read(2*8))
        else:
            self.rastr = "Unknown"
            self.decstr = "Unknown"
            (self.dt, self.startT) = struct.unpack(swapchar+"dd", test)
        (self.endT, self.tepoch, self.bepoch, self.avgvoverc, self.lofreq, \
         self.chan_wid, self.bestdm) = struct.unpack(swapchar+"d"*7, infile.read(7*8))
        (self.topo_pow, tmp) = struct.unpack(swapchar+"f"*2, infile.read(2*4))
        (self.topo_p1, self.topo_p2, self.topo_p3) = struct.unpack(swapchar+"d"*3, \
                                                                   infile.read(3*8))
        (self.bary_pow, tmp) = struct.unpack(swapchar+"f"*2, infile.read(2*4))
        (self.bary_p1, self.bary_p2, self.bary_p3) = struct.unpack(swapchar+"d"*3, \
                                                                   infile.read(3*8))
        (self.fold_pow, tmp) = struct.unpack(swapchar+"f"*2, infile.read(2*4))
        (self.fold_p1, self.fold_p2, self.fold_p3) = struct.unpack(swapchar+"d"*3, \
                                                                   infile.read(3*8))
        (self.orb_p, self.orb_e, self.orb_x, self.orb_w, self.orb_t, self.orb_pd, \
         self.orb_wd) = struct.unpack(swapchar+"d"*7, infile.read(7*8))
        self.dms = Num.asarray(struct.unpack(swapchar+"d"*self.numdms, \
                                             infile.read(self.numdms*8)))
        if self.numdms==1:
            self.dms = self.dms[0]
        self.periods = Num.asarray(struct.unpack(swapchar+"d"*self.numperiods, \
                                                 infile.read(self.numperiods*8)))
        self.pdots = Num.asarray(struct.unpack(swapchar+"d"*self.numpdots, \
                                               infile.read(self.numpdots*8)))
	self.numprofs = self.nsub*self.npart
        if (swapchar=='<'):  # little endian
            self.profs = Num.zeros((self.npart, self.nsub, self.proflen), typecode='d')
            for ii in range(self.npart):
                for jj in range(self.nsub):
                    self.profs[ii,jj,:] = fread(infile, self.proflen, 'd')
        else:
            self.profs = Num.asarray(struct.unpack(swapchar+"d"*self.numprofs*self.proflen, \
                                                   infile.read(self.numprofs*self.proflen*8)))
            self.profs = Num.reshape(self.profs, (self.npart, self.nsub, self.proflen))
        if (self.numchan==1):
            try:
                idata = infodata.infodata(self.filenm[:self.filenm.rfind('.')]+".inf")
                if idata.waveband=="Radio":
                    self.bestdm = idata.DM
                    self.numchan = idata.numchan
                else: # i.e. for events
                    self.bestdm = 0.0
                    self.numchan = 1
            except IOError:
                print "Warning!  Can't open the .inf file for "+filename+"!"
	self.binspersec = self.fold_p1*self.proflen
	self.chanpersub = self.numchan/self.nsub
	self.subdeltafreq = self.chan_wid*self.chanpersub
	self.hifreq = self.lofreq + (self.numchan-1)*self.chan_wid
	self.losubfreq = self.lofreq + self.subdeltafreq - self.chan_wid
	self.subfreqs = Num.arange(self.nsub, typecode='d')*self.subdeltafreq + \
                        self.losubfreq
        self.subdelays_bins = Num.zeros(self.nsub, typecode='d')
        self.killed_subbands = []
        self.killed_intervals = []
        self.pts_per_fold = []
	# Note: a foldstats struct is read in as a group of 7 doubles
	# the correspond to, in order: 
	#    numdata, data_avg, data_var, numprof, prof_avg, prof_var, redchi
        self.stats = Num.zeros((self.npart, self.nsub, 7), typecode='d')
	for ii in range(self.npart):
	    currentstats = self.stats[ii]
	    for jj in range(self.nsub):
		if (swapchar=='<'):  # little endian
		    currentstats[jj] = fread(infile, 7, 'd')
		else:
		    currentstats[jj] = Num.asarray(struct.unpack(swapchar+"d"*7, \
				                                 infile.read(7*8)))
            self.pts_per_fold.append(self.stats[ii][0][0])  # numdata from foldstats
        self.start_secs = umath.add.accumulate([0]+self.pts_per_fold[:-1])*self.dt
        self.pts_per_fold = Num.asarray(self.pts_per_fold)
        self.mid_secs = self.start_secs + 0.5*self.dt*self.pts_per_fold
        if (not self.tepoch==0.0):
            self.start_topo_MJDs = self.start_secs/86400.0 + self.tepoch
            self.mid_topo_MJDs = self.mid_secs/86400.0 + self.tepoch
        if (not self.bepoch==0.0):
            self.start_bary_MJDs = self.start_secs/86400.0 + self.bepoch
            self.mid_bary_MJDs = self.mid_secs/86400.0 + self.bepoch
        self.Nfolded = umath.add.reduce(self.pts_per_fold)
        self.T = self.Nfolded*self.dt
        self.avgprof = Num.sum(Num.ravel(self.profs))/self.proflen
        self.varprof = self.calc_varprof()
        infile.close()
        self.barysubfreqs = None
        if self.avgvoverc==0:
            if self.candnm.startswith("PSR_"):
                # If this doesn't work, we should try to use the barycentering calcs
                # in the presto module.
                try:
                    self.polycos = polycos.polycos(self.candnm.lstrip("PSR_"),
                                                   filenm=self.pfd_filename+".polycos")
                    midMJD = self.tepoch + 0.5*self.T/86400.0
                    self.avgvoverc = self.polycos.get_voverc(int(midMJD), midMJD-int(midMJD))
                    sys.stderr.write("Approximate Doppler velocity (in c) is:  %.4g\n"%self.avgvoverc)
                    # Make the Doppler correction
                    self.barysubfreqs = self.subfreqs*(1.0+self.avgvoverc)
                except IOError:
                    self.polycos = 0
        if self.barysubfreqs is None:
            self.barysubfreqs = self.subfreqs

    def __str__(self):
        out = ""
        for k, v in self.__dict__.items():
            if k[:2]!="__":
                if type(self.__dict__[k]) is StringType:
                    out += "%10s = '%s'\n" % (k, v)
                elif type(self.__dict__[k]) is IntType:
                    out += "%10s = %d\n" % (k, v)
                elif type(self.__dict__[k]) is FloatType:
                    out += "%10s = %-20.15g\n" % (k, v)
        return out

    def dedisperse(self, DM=None, interp=0):
        """
        dedisperse(DM=self.bestdm, interp=0):
            Rotate (internally) the profiles so that they are de-dispersed
                at a dispersion measure of DM.  Use sinc-interpolation if
                'interp' is non-zero (NOTE: It is _on_ by default!).
        """
        if DM is None:
            DM = self.bestdm
        self.subdelays = psr_utils.delay_from_DM(DM, self.barysubfreqs)
	self.hifreqdelay = self.subdelays[-1]
	self.subdelays = self.subdelays-self.hifreqdelay
        delaybins = self.subdelays*self.binspersec - self.subdelays_bins
        if interp:
            interp_factor = 16
            new_subdelays_bins = umath.floor(delaybins*interp_factor+0.5)/float(interp_factor)
            for ii in range(self.npart):
                for jj in range(self.nsub):
                    tmp_prof = self.profs[ii,jj,:]
                    self.profs[ii,jj] = psr_utils.interp_rotate(tmp_prof, delaybins[jj],
                                                                zoomfact=interp_factor)
            # Note: Since the interpolation process slightly changes the values of the
            # profs, we need to re-calculate the average profile value
            self.avgprof = Num.sum(Num.ravel(self.profs))/self.proflen
        else:
            new_subdelays_bins = umath.floor(delaybins+0.5)
            for ii in range(self.nsub):
                rotbins = int(new_subdelays_bins[ii])%self.proflen
                if rotbins:  # i.e. if not zero
                    subdata = self.profs[:,ii,:]
                    self.profs[:,ii] = Num.concatenate((subdata[:,rotbins:],
                                                        subdata[:,:rotbins]), 1)
        self.subdelays_bins += new_subdelays_bins
        self.sumprof = Num.sum(Num.sum(self.profs))
        if umath.fabs(Num.sum(self.sumprof)/self.proflen - self.avgprof) > 1.0:
            print "self.avgprof is not the correct value!"

    def combine_profs(self, new_npart, new_nsub):
        """
        combine_profs(self, new_npart, new_nsub):
            Combine intervals and/or subbands together and return a new
                array of profiles.
        """
        if (self.npart % new_npart):
            print "Warning!  The new number of intervals (%d) is not a" % new_npart
            print "          divisor of the original number of intervals (%d)!"  % self.npart
            print "Doing nothing."
            return None
        if (self.nsub % new_nsub):
            print "Warning!  The new number of subbands (%d) is not a" % new_nsub
            print "          divisor of the original number of subbands (%d)!"  % self.nsub
            print "Doing nothing."
            return None

        dp = self.npart/new_npart
        ds = self.nsub/new_nsub

        newprofs = Num.zeros((new_npart, new_nsub, self.proflen), 'd')
        for ii in range(new_npart):
            # Combine the subbands if required
            if (self.nsub > 1):
                for jj in range(new_nsub):
                    subprofs = umath.add.reduce(self.profs[:,jj*ds:(jj+1)*ds], 1)
                    # Combine the time intervals
                    newprofs[ii][jj] = umath.add.reduce(subprofs[ii*dp:(ii+1)*dp])
            else:
                newprofs[ii][0] = umath.add.reduce(self.profs[ii*dp:(ii+1)*dp,0])
        return newprofs

    def kill_intervals(self, intervals):
        """
        kill_intervals(intervals):
            Set all the subintervals (internally) from the list of
                subintervals to all zeros, effectively 'killing' them.
        """
        for part in intervals:
            self.profs[part,:,:] *= 0.0
            self.killed_intervals.append(part)
        # Update the stats
        self.avgprof = Num.sum(Num.ravel(self.profs))/self.proflen
        self.varprof = self.calc_varprof()

    def kill_subbands(self, subbands):
        """
        kill_subbands(subbands):
            Set all the profiles (internally) from the list of
                subbands to all zeros, effectively 'killing' them.
        """
        for sub in subbands:
            self.profs[:,sub,:] *= 0.0
            self.killed_subbands.append(sub)
        # Update the stats
        self.avgprof = Num.sum(Num.ravel(self.profs))/self.proflen
        self.varprof = self.calc_varprof()

    def plot_sumprof(self, device='/xwin'):
        """
        plot_sumprof(self, device='/xwin'):
            Plot the dedispersed and summed profile.
        """
        if not self.__dict__.has_key('subdelays'):
            print "Dedispersing first..."
            self.dedisperse()
        normprof = self.sumprof - min(self.sumprof)
        normprof /= max(normprof)
        Pgplot.plotxy(normprof, labx="Phase Bins", laby="Normalized Flux",
                      device=device)

    def greyscale(self, array2d, **kwargs):
        """
        greyscale(array2d, **kwargs):
            Plot a 2D array as a greyscale image using the same scalings
                as in prepfold.
        """
        # Use the same scaling as in prepfold_plot.c
        global_max = Num.maximum.reduce(Num.maximum.reduce(array2d))
        min_parts = Num.minimum.reduce(array2d, 1)
        array2d = (array2d-min_parts[:,Num.NewAxis])/global_max
        Pgplot.plot2d(array2d, image='antigrey', **kwargs)

    def plot_intervals(self, phasebins='All', device='/xwin'):
        """
        plot_intervals(self, phasebins='All', device='/xwin'):
            Plot the subband-summed profiles vs time.  Restrict
                the bins in the plot to the (low:high) slice defined
                by the phasebins option if it is a tuple (low,high)
                instead of the string 'All'. 
        """
        if not self.__dict__.has_key('subdelays'):
            print "Dedispersing first..."
            self.dedisperse()
        if phasebins is not 'All':
            lo, hi = phasebins
            profs = Num.sum(self.profs[:,:,lo:hi], 1)
        else:
            lo, hi = 0.0, self.proflen
            profs = Num.sum(self.profs, 1)
        self.greyscale(profs, rangex=[lo, hi], rangey=[0.0, self.npart],
                       labx="Phase Bins", labx2="Pulse Phase", laby="Time Intervals",
                       rangex2=Num.asarray([lo, hi])*1.0/self.proflen,
                       laby2="Time (s)", rangey2=[0.0, self.T], 
                       device=device)

    def plot_subbands(self, phasebins='All', device='/xwin'):
        """
        plot_subbands(self, phasebins='All', device='/xwin'):
            Plot the interval-summed profiles vs subband.  Restrict
                the bins in the plot to the (low:high) slice defined
                by the phasebins option if it is a tuple (low,high)
                instead of the string 'All'. 
        """
        if not self.__dict__.has_key('subdelays'):
            print "Dedispersing first..."
            self.dedisperse()
        if phasebins is not 'All':
            lo, hi = phasebins
            profs = Num.sum(self.profs[:,:,lo:hi])
        else:
            lo, hi = 0.0, self.proflen
            profs = Num.sum(self.profs)
        lof = self.lofreq - 0.5*self.chan_wid
        hif = lof + self.chan_wid*self.numchan
        self.greyscale(profs, rangex=[lo, hi], rangey=[0.0, self.nsub],
                      labx="Phase Bins", labx2="Pulse Phase", laby="Subbands",
                      rangex2=Num.asarray([lo, hi])*1.0/self.proflen,
                      laby2="Frequency (MHz)", rangey2=[lof, hif],
                      device=device)

    def calc_varprof(self):
        """
        calc_varprof(self):
            This function calculates the summed profile variance of the
                current pfd file.  Killed profiles are ignored.
        """
        varprof = 0.0
        for part in range(self.npart):
            if part in self.killed_intervals: continue
            for sub in range(self.nsub):
                if sub in self.killed_subbands: continue
                varprof += self.stats[part][sub][5] # foldstats prof_var
        return varprof

    def calc_redchi2(self, prof=None, avg=None, var=None):
        """
        calc_redchi2(self, prof=None, avg=None, var=None):
            Return the calculated reduced-chi^2 of the current summed profile.
        """
        if not self.__dict__.has_key('subdelays'):
            print "Dedispersing first..."
            self.dedisperse()
        if prof is None:  prof = self.sumprof
        if avg is None:  avg = self.avgprof
        if var is None:  var = self.varprof
        return Num.sum((prof-avg)**2.0/var)/(len(prof)-1.0)

    def plot_chi2_vs_DM(self, loDM, hiDM, N=100, interp=0, device='/xwin'):
        """
        plot_chi2_vs_DM(self, loDM, hiDM, N=100, interp=0, device='/xwin'):
            Plot (and return) an array showing the reduced-chi^2 versus
                DM (N DMs spanning loDM-hiDM).  Use sinc_interpolation
                if 'interp' is non-zero.
        """
        # Sum the profiles in time
        sumprofs = Num.sum(self.profs)
        if not interp:
            profs = sumprofs
        else:
            profs = Num.zeros(Num.shape(sumprofs), typecode='d')
        DMs = psr_utils.span(loDM, hiDM, N)
        chis = Num.zeros(N, typecode='f')
        subdelays_bins = self.subdelays_bins.copy()
        for ii, DM in enumerate(DMs):
            subdelays = psr_utils.delay_from_DM(DM, self.barysubfreqs)
            hifreqdelay = subdelays[-1]
            subdelays = subdelays - hifreqdelay
            delaybins = subdelays*self.binspersec - subdelays_bins
            if interp:
                interp_factor = 16
                for jj in range(self.nsub):
                    profs[jj] = psr_utils.interp_rotate(sumprofs[jj], delaybins[jj],
                                                        zoomfact=interp_factor)
                # Note: Since the interpolation process slightly changes the values of the
                # profs, we need to re-calculate the average profile value
                avgprof = Num.sum(Num.ravel(profs))/self.proflen
            else:
                new_subdelays_bins = umath.floor(delaybins+0.5)
                for jj in range(self.nsub):
                    profs[jj] = psr_utils.rotate(profs[jj], int(new_subdelays_bins[jj]))
                subdelays_bins += new_subdelays_bins
                avgprof = self.avgprof
            sumprof = Num.sum(profs)
            chis[ii] = self.calc_redchi2(prof=sumprof, avg=avgprof)
        # Now plot it
        Pgplot.plotxy(chis, DMs, labx="DM", laby="Reduced-\gx\u2\d", device=device)
        return (chis, DMs)

    def plot_chi2_vs_sub(self, device='/xwin'):
        """
        plot_chi2_vs_sub(self, device='/xwin'):
            Plot (and return) an array showing the reduced-chi^2 versus
                the subband number.
        """
        # Sum the profiles in each subband
        profs = Num.sum(self.profs)
        # Compute the averages and variances for the subbands
        avgs = Num.add.reduce(profs, 1)/self.proflen
        vars = []
        for sub in range(self.nsub):
            var = 0.0
            if sub in self.killed_subbands:
                vars.append(var)
                continue
            for part in range(self.npart):
                if part in self.killed_intervals:
                    continue
                var += self.stats[part][sub][5] # foldstats prof_var
            vars.append(var)
        chis = Num.zeros(self.nsub, typecode='f')
        for ii in range(self.nsub):
            chis[ii] = self.calc_redchi2(prof=profs[ii], avg=avgs[ii], var=vars[ii])
        # Now plot it
        Pgplot.plotxy(chis, labx="Subband Number", laby="Reduced-\gx\u2\d",
                      rangey=[0.0, max(chis)*1.1], device=device)
        return chis

    def estimate_offsignal_redchi2(self):
        """
        estimate_offsignal_redchi2():
            Estimate the reduced-chi^2 off of the signal based on randomly shifting
                and summing all of the component profiles.  
        """
        numtrials = 20
        redchi2s = []
        for count in range(numtrials):
            prof = Num.zeros(self.proflen, typecode='d')
            for ii in range(self.npart):
                for jj in range(self.nsub):
                    tmpprof = copy.copy(self.profs[ii][jj])
                    prof += psr_utils.rotate(tmpprof, random.randrange(0,self.proflen))
            redchi2s.append(self.calc_redchi2(prof=prof))
        return psr_utils.mean(redchi2s)

    def adjust_fold_frequency(self, phasebins, profs=None, shiftsubs=False):
        """
        adjust_fold_frequency(phasebins, profs=None, shiftsubs=False):
            Linearly shift the intervals by phasebins over the course of
                the observation in order to change the apparent folding
                frequency.  Return a 2D array containing the de-dispersed
                profiles as a function of time (i.e. shape = (npart, proflen)),
				and the reduced chi^2 of the resulting summed profile.
                If profs is not None, then use profs instead of self.profs.
				If shiftsubs is not False, then actually correct the subbands
				instead of a 2D projection of them.
        """
        if not self.__dict__.has_key('subdelays'):
            print "Dedispersing first..."
            self.dedisperse()
        if shiftsubs:
            print "Shifting all the subbands..."
            if profs is None:
                profs = self.profs
            for ii in range(self.npart):
                bins_to_shift = int(round(float(ii)/self.npart * phasebins))
                for jj in range(self.nsub):
                    profs[ii,jj] = psr_utils.rotate(profs[ii,jj], bins_to_shift)
            redchi = self.calc_redchi2(prof=Num.sum(Num.sum(profs)))
        else:
            print "Shifting just the projected intervals (not individual subbands)..."
            if profs is None:
                profs = Num.sum(self.profs, 1)
            for ii in range(self.npart):
                bins_to_shift = int(round(float(ii)/self.npart * phasebins))
                profs[ii] = psr_utils.rotate(profs[ii], bins_to_shift)
            redchi = self.calc_redchi2(prof=Num.sum(profs))
        print "New reduced-chi^2 =", redchi
        return profs, redchi

    def dynamic_spectra(self, onbins, combineints=1, combinechans=1,
                        calibrate=True, plot=True, device='/xwin'):
        """
        dynamic_spectra(onbins, combineints=1, combinechans=1,
                        calibrate=True, plot=True, device='/xwin'):
            Return (and plot) the dynamic spectrum (DS) resulting
                from the folds in the .pfd assuming that the pulsar
                is 'on' during the bins specified in 'onbins' and
                off elsewhere (ON-OFF).  If calibrate is True, the
                DS will be (ON-OFF)/OFF.  combineints and combinechans
                describe how many adjacent intervals or frequency
                channels will be combined when making the DS.
        """
        # Determine the indices of the off-pulse region
        indices = Num.arange(self.proflen)
        Num.put(indices, Num.asarray(onbins), -1)
        offbins = Num.compress(indices >= 0, Num.arange(self.proflen))
        numon = len(onbins)
        numoff = len(offbins)
        # De-disperse if required first
        if not self.__dict__.has_key('subdelays'):
            print "Dedispersing first..."
            self.dedisperse()
        # The following is the average offpulse level
        offpulse = Num.sum(Num.take(self.profs, offbins, 2), 2)/float(numoff)
        # The following is the average onpulse level
        onpulse  = Num.sum(Num.take(self.profs,  onbins, 2), 2)/float(numon)
        # Now make the DS
        self.DS = onpulse - offpulse
        self.DSnpart = self.npart
        self.DSstart_secs = self.start_secs
        self.DSintdt = self.DSstart_secs[1] - self.DSstart_secs[0]
        self.DSnsub = self.nsub
        self.DSsubfreqs = self.subfreqs
        self.DSsubdeltafreq = self.subdeltafreq
        if (calibrate):
            self.DS /= offpulse
        # Combine intervals if required
        if (combineints > 1):
            # First chop off any extra intervals
            if (self.npart % combineints):
                self.DSnpart = (self.npart/combineints) * combineints
                self.DS = self.DS[:self.DSnpart,:]
            # Now reshape and add the neighboring intervals
            self.DS = Num.reshape(self.DS, (self.DSnpart/combineints,
                                            combineints, self.DSnsub))
            print Num.shape(self.DS)
            self.DS = Num.sum(self.DS, 1)
            self.DSstart_secs = self.DSstart_secs[::combineints]
            self.DSintdt *= combineints
            self.DSnpart /= combineints
        # Combine channels if required
        if (combinechans > 1):
            # First chop off any extra channels
            if (self.nsub % combinechans):
                self.DSnsub = (self.nsub/combinechans) * combinechans
                self.DS = self.DS[:,:self.DSnsub]
            # Now reshape and add the neighboring intervals
            self.DS = Num.reshape(self.DS, (self.DSnpart,
                                            self.DSnsub/combinechans, combinechans))
            self.DS = Num.sum(self.DS, 2)
            self.DSsubfreqs = psr_utils.running_avg(self.subfreqs[:self.DSnsub], combinechans)
            self.DSsubdeltafreq *= combinechans
            self.DSnsub /= combinechans
        print "DS shape = ", Num.shape(self.DS)
        # Plot it if required
        if plot:
            lof = self.subfreqs[0]-0.5*self.DSsubdeltafreq
            hif = self.subfreqs[-1]+0.5*self.DSsubdeltafreq
            lot = 0.0
            hit = self.DSstart_secs[-1] + self.DSintdt
            self.greyscale(self.DS, rangex=[lof, hif], rangey=[lot, hit],
                           labx="Frequency (MHz)", labx2="Subband Number",
                           laby="Time (s)", laby2="Interval Number",
                           rangex2=[0, self.DSnsub], rangey2=[0, self.DSnpart], 
                           device=device)
        return self.DS

if __name__ == "__main__":
    import sys
    
    #testpfd = "/home/ransom/tmp_pfd/M5_52725_W234_PSR_1518+0204A.pfd"
    #testpfd = "/home/ransom/tmp_pfd/M13_52724_W234_PSR_1641+3627C.pfd"
    testpfd = "M13_53135_W34_rficlean_DM30.10_PSR_1641+3627C.pfd"

    tp = pfd(testpfd)

    if (0):
        print tp.start_secs
        print tp.mid_secs
        print tp.start_topo_MJDs
        print tp.mid_topo_MJDs
        print tp.T

    #tp.kill_subbands([6,7,8,9,30,31,32,33])
    #tp.kill_intervals([2,3,4,5,6])

    #tp.plot_chi2_vs_sub()
    #(chis, DMs) = tp.plot_chi2_vs_DM(0.0, 50.0, 501, interp=1)
    #best_index = Num.argmax(chis)
    #print "Best DM = ", DMs[best_index]

    (chis, DMs) = tp.plot_chi2_vs_DM(0.0, 50.0, 501)
    best_index = Num.argmax(chis)
    print "Best DM = ", DMs[best_index]
    
    tp.dedisperse()
    tp.plot_subbands()
    tp.plot_sumprof()
    print "DM =", tp.bestdm, "gives reduced chi^2 =", tp.calc_redchi2()

    tp.dedisperse(27.0)
    tp.plot_subbands()
    tp.plot_sumprof()
    print "DM = 27.0 gives reduced chi^2 =", tp.calc_redchi2()

    tp.dedisperse(33.0)
    tp.plot_subbands()
    tp.plot_sumprof()
    print "DM = 33.0 gives reduced chi^2 =", tp.calc_redchi2()

    tp.plot_intervals()
