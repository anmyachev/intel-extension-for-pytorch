import torch
import copy

from .. import modules

def replace_dropout_with_identity(model):
    # replace dropout with identity during inference, so that aten::dropout won't be on the JIT graph.
    # This optimization may provide more fusion opportunites on the graph.
    if not model.training:
        for child_name, child in model.named_children():
            if isinstance(child, torch.nn.Dropout):
                setattr(model, child_name, torch.nn.Identity())
            else:
                replace_dropout_with_identity(child)

def replace_lstm_with_ipex_lstm(model):
    # replace lstm with ipex lstm during inference
    # does not support the case where model itself is torch.nn.LSTM
    for child_name, child in model.named_children():
        if isinstance(child, torch.nn.LSTM):
            assert hasattr(child, "weight_ih_l0"), "torch.nn.LSTM should have weight_ih_l0"
            ipex_lstm = modules.IpexLSTM(child.input_size, child.hidden_size,
                child.num_layers, child.bias, child.batch_first,
                child.dropout, child.bidirectional, child.proj_size,
                child.weight_ih_l0.device, child.weight_ih_l0.dtype)
            ipex_lstm.__dict__ = copy.deepcopy(child.__dict__)
            setattr(model, child_name, ipex_lstm)
        else:
            replace_lstm_with_ipex_lstm(child)

def convert_module_data_type(module, dtype):
    # convert weights(bias) of module to dtype to reduce dtype reorder
    module_convert_list = [torch.nn.Conv2d,
                           torch.nn.Linear,
                           torch.nn.Embedding,
                           torch.nn.LSTM]
    for module_cls in module_convert_list:
        if isinstance(module, module_cls):
            if module_cls is torch.nn.LSTM:
                for name, param in module.named_parameters():
                    getattr(module, name)
                    casted_data = getattr(getattr(module, name), "data").detach().clone().to(dtype)
                    setattr(getattr(module, name), "data", casted_data)
            else:
                weight_data = module.weight.detach().clone().to(dtype)
                module.weight.data = weight_data
                if hasattr(module, 'bias') and module.bias is not None:
                    bias_data = module.bias.detach().clone().to(dtype)
                    module.bias.data = bias_data
                break
    for child in module.children():
        convert_module_data_type(child, dtype)
    return module
