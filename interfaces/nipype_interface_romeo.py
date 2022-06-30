from nipype.interfaces.base import  traits, CommandLine, BaseInterfaceInputSpec, TraitedSpec, File, InputMultiPath
import nibabel as nib
import numpy as np


## Romeo wrapper single-echo (MapNode)
class RomeoInputSpec(BaseInterfaceInputSpec):
    phase = File(mandatory=True, exists=True, argstr="--phase %s")
    #mask = File(mandatory=False, exists=True, argstr="--mask %s")
    #TE = traits.Float(desc='Echo Time [sec]', mandatory=True, argstr="-t %f")
    mag = File(mandatory=False, exists=True, argstr="--mag %s")
    out_file = File(argstr="--output %s", name_source=['phase'], name_template='%s_unwrapped.nii.gz')

class RomeoOutputSpec(TraitedSpec):
    out_file = File()

class RomeoInterface(CommandLine):
    input_spec = RomeoInputSpec
    output_spec = RomeoOutputSpec
    _cmd = "romeoApp.jl"


## Romeo wrapper multi-echo (Node)
class RomeoB0InputSpec(BaseInterfaceInputSpec):
    phase = InputMultiPath(mandatory=True, exists=True)
    mag = InputMultiPath(mandatory=True, exists=True)
    TE = traits.ListFloat(desc='Echo Time [sec]', mandatory=True, argstr="-t %s")

class RomeoB0OutputSpec(TraitedSpec):
    out_file = File('B0.nii', usedefault=True)

class RomeoB0Interface(CommandLine):
    input_spec = RomeoB0InputSpec
    output_spec = RomeoB0OutputSpec
    _cmd = "romeoApp.jl -B --no-rescale --phase-offset-correction --phase multi-echo-phase.nii --mag multi-echo-mag.nii"

    def _run_interface(self, runtime):
        save_multi_echo(self.inputs.phase, "multi-echo-phase.nii")
        save_multi_echo(self.inputs.mag, "multi-echo-mag.nii")
        super(RomeoB0Interface, self)._run_interface(runtime)
    
def save_multi_echo(in_files, fn_path):
    image4d = np.stack([nib.load(f).get_fdata() for f in in_files], -1)
    sample_nii = nib.load(in_files[0])
    nib.save(nib.nifti1.Nifti1Image(image4d, affine=sample_nii.affine, header=sample_nii.header), fn_path)
    