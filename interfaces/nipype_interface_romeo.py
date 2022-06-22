from nipype.interfaces.base import  traits, CommandLine, BaseInterfaceInputSpec, TraitedSpec, File
from nipype.utils.filemanip import fname_presuffix, split_filename


## Romeo wrapper
class RomeoInputSpec(BaseInterfaceInputSpec):
    #phase = File(position=0, mandatory=True, exists=True, argstr="--no-rescale --phase-offset-correction --phase %s")
    phase = File(position=0, mandatory=True, exists=True, argstr="--phase %s")
    #mask = File(mandatory=False, exists=True, argstr="--mask %s")
    TE = traits.Float(position=1, desc='Echo Time [sec]', mandatory=True, argstr="-t %f")
    mag = File(position=2, mandatory=False, exists=True, argstr="--mag %s")
    out_file = File(position=3, argstr="--output %s", name_source=['phase'], name_template='%s_unwrapped.nii.gz')
    # TODO use out_suffix?

class RomeoOutputSpec(TraitedSpec):
    out_file = File()

class RomeoInterface(CommandLine):
    input_spec = RomeoInputSpec
    output_spec = RomeoOutputSpec
    _cmd = "romeo.jl"
    