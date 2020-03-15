Used Tensorflow nightly version, for whatever reason it needed that to work properly. 

The first time you run it, it will create the tokenizers, which will take quite a while, but each subsequent run will just read these from the output files that it creates. 
The code for training is commented out, and it will immediately read the last checkpoint that was created to train on and product output based on that.

More explanation is available on https://www.tensorflow.org/tutorials/text/transformer
I'd probably start there and look at the full source to see what's going on 
